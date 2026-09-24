import json
from abc import ABC,abstractmethod
from datetime import datetime,timedelta,timezone

from flask import current_app

from roya.common.db import db_connection


class NotificationAdapter(ABC):
    @abstractmethod
    def send(self,*,recipient:str,subject:str,body:str): ...


class NotificationService:
    MAX_EMAIL_ATTEMPTS=5

    def __init__(self,adapter:NotificationAdapter|None=None):
        self.adapter=adapter

    def send(self,*,recipient,subject,body):
        if not self.adapter:
            return {"sent":False,"reason":"notification_adapter_not_configured"}
        return self.adapter.send(recipient=recipient,subject=subject,body=body)

    @staticmethod
    def _absolute_url(path):
        base=(current_app.config.get("APP_URL") or "").rstrip("/")
        return f"{base}{path}" if base else path

    @staticmethod
    def _insert_in_app(conn,*,user_id,reservation_id,event_type,title,body,href):
        conn.execute(
            """insert into notifications(
                 user_id,reservation_id,channel,event_type,recipient,status,payload,sent_at
               ) values(%s,%s,'in_app',%s,%s,'sent',%s::jsonb,now())""",
            (
                user_id,
                reservation_id,
                event_type,
                str(user_id),
                json.dumps({"title":title,"body":body,"href":href}),
            ),
        )

    @staticmethod
    def _queue_email(conn,*,user_id,reservation_id,event_type,recipient,subject,body,href):
        row=conn.execute(
            """insert into notifications(
                 user_id,reservation_id,channel,event_type,recipient,status,payload,next_attempt_at
               ) values(%s,%s,'email',%s,%s,'queued',%s::jsonb,now())
               returning id""",
            (
                user_id,
                reservation_id,
                event_type,
                recipient,
                json.dumps({
                    "subject":subject,
                    "body":body,
                    "href":href,
                }),
            ),
        ).fetchone()
        return str(row["id"])

    @staticmethod
    def _smtp_configured():
        return bool(
            current_app.config.get("SMTP_HOST")
            and current_app.config.get("SMTP_FROM")
        )

    def _adapter(self):
        if self.adapter:
            return self.adapter
        from .smtp import SmtpNotificationAdapter
        self.adapter=SmtpNotificationAdapter()
        return self.adapter

    def deliver_pending_emails(self,limit=50,notification_ids=None):
        if not self._smtp_configured():
            return {
                "configured":False,
                "checked":0,
                "sent":0,
                "retrying":0,
                "failed":0,
            }

        params=[]
        where=["channel='email'","status='queued'","next_attempt_at<=now()"]
        if notification_ids:
            where.append("id=any(%s::uuid[])")
            params.append(list(notification_ids))
        params.append(max(1,min(int(limit),200)))

        with db_connection() as conn:
            candidates=list(conn.execute(
                f"""select id from notifications
                    where {' and '.join(where)}
                    order by created_at asc
                    limit %s""",
                tuple(params),
            ).fetchall())

        sent=0
        retrying=0
        failed=0
        adapter=self._adapter()

        for candidate in candidates:
            notification_id=str(candidate["id"])

            with db_connection() as conn:
                claimed=conn.execute(
                    """update notifications
                       set attempts=attempts+1,
                           next_attempt_at=now()+interval '5 minutes',
                           last_error=null
                       where id=%s
                         and channel='email'
                         and status='queued'
                         and next_attempt_at<=now()
                       returning id,recipient,payload,attempts""",
                    (notification_id,),
                ).fetchone()
                conn.commit()

            if not claimed:
                continue

            payload=claimed["payload"] or {}
            if isinstance(payload,str):
                payload=json.loads(payload)

            error=None
            try:
                result=adapter.send(
                    recipient=claimed["recipient"],
                    subject=payload.get("subject") or "iRoya update",
                    body=payload.get("body") or "",
                )
                if not result.get("sent"):
                    error=str(result.get("reason") or "notification_send_failed")
            except Exception as exc:
                error=str(exc)[:1000]

            if error is None:
                with db_connection() as conn:
                    conn.execute(
                        """update notifications
                           set status='sent',sent_at=now(),last_error=null
                           where id=%s""",
                        (notification_id,),
                    )
                    conn.commit()
                sent+=1
                continue

            attempts=int(claimed["attempts"] or 1)
            terminal=attempts>=self.MAX_EMAIL_ATTEMPTS
            delay_minutes=min(5*(2**max(attempts-1,0)),120)
            next_attempt=datetime.now(timezone.utc)+timedelta(minutes=delay_minutes)
            with db_connection() as conn:
                conn.execute(
                    """update notifications
                       set status=%s,last_error=%s,next_attempt_at=%s
                       where id=%s""",
                    ("failed" if terminal else "queued",error[:1000],next_attempt,notification_id),
                )
                conn.commit()
            if terminal:
                failed+=1
            else:
                retrying+=1

        return {
            "configured":True,
            "checked":len(candidates),
            "sent":sent,
            "retrying":retrying,
            "failed":failed,
        }

    def _deliver_new(self,email_ids):
        if not email_ids:
            return {"configured":self._smtp_configured(),"checked":0,"sent":0,"retrying":0,"failed":0}
        return self.deliver_pending_emails(
            limit=len(email_ids),
            notification_ids=email_ids,
        )

    def notify_reservation_created(self,reservation_id):
        email_ids=[]
        try:
            with db_connection() as conn:
                with conn.transaction():
                    r=conn.execute(
                        """select r.id,r.reference,r.user_id,r.organization_id,r.status,r.guest_email,
                                  p.name property_name
                           from reservations r
                           join properties p on p.id=r.property_id
                           where r.id=%s""",
                        (reservation_id,),
                    ).fetchone()
                    if not r:
                        return {"created":0}

                    guest_title={
                        "confirmed":"Reservation confirmed",
                        "held":"Room held for you",
                        "pending_confirmation":"Reservation request sent",
                    }.get(r["status"],"Reservation created")
                    guest_body={
                        "confirmed":f"{r['property_name']} is confirmed under {r['reference']}.",
                        "held":f"{r['property_name']} is temporarily held while payment is completed.",
                        "pending_confirmation":f"{r['property_name']} is reviewing request {r['reference']}.",
                    }.get(r["status"],f"Reservation {r['reference']} was created.")
                    guest_href=f"/reservation/{r['id']}"
                    self._insert_in_app(
                        conn,
                        user_id=r["user_id"],
                        reservation_id=r["id"],
                        event_type="reservation.created",
                        title=guest_title,
                        body=guest_body,
                        href=guest_href,
                    )
                    email_ids.append(self._queue_email(
                        conn,
                        user_id=r["user_id"],
                        reservation_id=r["id"],
                        event_type="reservation.created",
                        recipient=r["guest_email"],
                        subject=f"iRoya: {guest_title} · {r['reference']}",
                        body=f"{guest_body}\n\nView reservation: {self._absolute_url(guest_href)}",
                        href=guest_href,
                    ))

                    members=list(conn.execute(
                        """select om.user_id,u.email
                           from organization_members om
                           join auth.users u on u.id=om.user_id
                           where om.organization_id=%s
                             and om.status='active'
                             and om.role in ('owner','manager','reservations')""",
                        (r["organization_id"],),
                    ).fetchall())
                    hotel_title={
                        "pending_confirmation":"Reservation needs approval",
                        "held":"Payment hold created",
                        "confirmed":"New reservation",
                    }.get(r["status"],"Reservation update")
                    hotel_body=f"{r['reference']} for {r['property_name']} is {r['status'].replace('_',' ')}."
                    hotel_href="/partner#reservations"
                    for member in members:
                        self._insert_in_app(
                            conn,
                            user_id=member["user_id"],
                            reservation_id=r["id"],
                            event_type="partner.reservation_created",
                            title=hotel_title,
                            body=hotel_body,
                            href=hotel_href,
                        )
                        if member["email"]:
                            email_ids.append(self._queue_email(
                                conn,
                                user_id=member["user_id"],
                                reservation_id=r["id"],
                                event_type="partner.reservation_created",
                                recipient=member["email"],
                                subject=f"iRoya hotel: {hotel_title} · {r['reference']}",
                                body=f"{hotel_body}\n\nOpen hotel workspace: {self._absolute_url(hotel_href)}",
                                href=hotel_href,
                            ))

            delivery=self._deliver_new(email_ids)
            return {
                "created":1+len(members),
                "emails_queued":len(email_ids),
                "delivery":delivery,
            }
        except Exception:
            return {"created":0,"error":"notification_write_failed"}

    def notify_guest_decision(self,reservation_id,status):
        email_ids=[]
        try:
            with db_connection() as conn:
                with conn.transaction():
                    r=conn.execute(
                        """select r.id,r.reference,r.user_id,r.guest_email,p.name property_name
                           from reservations r
                           join properties p on p.id=r.property_id
                           where r.id=%s""",
                        (reservation_id,),
                    ).fetchone()
                    if not r:
                        return {"created":0}
                    approved=status=="confirmed"
                    title="Reservation approved" if approved else "Reservation declined"
                    body=(
                        f"{r['property_name']} approved {r['reference']}."
                        if approved else
                        f"{r['property_name']} declined {r['reference']}."
                    )
                    href=f"/reservation/{r['id']}"
                    event_type="reservation.approved" if approved else "reservation.declined"
                    self._insert_in_app(
                        conn,
                        user_id=r["user_id"],
                        reservation_id=r["id"],
                        event_type=event_type,
                        title=title,
                        body=body,
                        href=href,
                    )
                    email_ids.append(self._queue_email(
                        conn,
                        user_id=r["user_id"],
                        reservation_id=r["id"],
                        event_type=event_type,
                        recipient=r["guest_email"],
                        subject=f"iRoya: {title} · {r['reference']}",
                        body=f"{body}\n\nView reservation: {self._absolute_url(href)}",
                        href=href,
                    ))
            delivery=self._deliver_new(email_ids)
            return {"created":1,"emails_queued":1,"delivery":delivery}
        except Exception:
            return {"created":0,"error":"notification_write_failed"}

    def notify_guest_status(self,reservation_id,status):
        email_ids=[]
        try:
            with db_connection() as conn:
                with conn.transaction():
                    r=conn.execute(
                        """select r.id,r.reference,r.user_id,r.guest_email,p.name property_name
                           from reservations r
                           join properties p on p.id=r.property_id
                           where r.id=%s""",
                        (reservation_id,),
                    ).fetchone()
                    if not r:
                        return {"created":0}
                    labels={
                        "checked_in":("Checked in",f"{r['reference']} is now checked in at {r['property_name']}."),
                        "checked_out":("Stay completed",f"{r['reference']} has been checked out."),
                        "no_show":("Reservation marked no-show",f"{r['property_name']} marked {r['reference']} as no-show."),
                    }
                    title,body=labels.get(status,("Reservation updated",f"{r['reference']} changed to {status}."))
                    href=f"/reservation/{r['id']}"
                    event_type="reservation."+status
                    self._insert_in_app(
                        conn,
                        user_id=r["user_id"],
                        reservation_id=r["id"],
                        event_type=event_type,
                        title=title,
                        body=body,
                        href=href,
                    )
                    email_ids.append(self._queue_email(
                        conn,
                        user_id=r["user_id"],
                        reservation_id=r["id"],
                        event_type=event_type,
                        recipient=r["guest_email"],
                        subject=f"iRoya: {title} · {r['reference']}",
                        body=f"{body}\n\nView reservation: {self._absolute_url(href)}",
                        href=href,
                    ))
            delivery=self._deliver_new(email_ids)
            return {"created":1,"emails_queued":1,"delivery":delivery}
        except Exception:
            return {"created":0,"error":"notification_write_failed"}

    def list_for_user(self,user_id,limit=100):
        with db_connection() as conn:
            return list(conn.execute(
                """select id,reservation_id,event_type,payload,read_at,created_at
                   from notifications
                   where user_id=%s and channel='in_app' and status='sent'
                   order by created_at desc
                   limit %s""",
                (user_id,limit),
            ).fetchall())

    def mark_read(self,user_id,notification_id):
        with db_connection() as conn:
            row=conn.execute(
                """update notifications set read_at=coalesce(read_at,now())
                   where id=%s and user_id=%s and channel='in_app'
                   returning id,read_at""",
                (notification_id,user_id),
            ).fetchone()
            conn.commit()
        return row

    def mark_all_read(self,user_id):
        with db_connection() as conn:
            cur=conn.execute(
                """update notifications set read_at=coalesce(read_at,now())
                   where user_id=%s and channel='in_app' and read_at is null""",
                (user_id,),
            )
            conn.commit()
        return {"updated":cur.rowcount}
