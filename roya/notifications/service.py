import json
from abc import ABC,abstractmethod

from roya.common.db import db_connection


class NotificationAdapter(ABC):
    @abstractmethod
    def send(self,*,recipient:str,subject:str,body:str): ...


class NotificationService:
    def __init__(self,adapter:NotificationAdapter|None=None):
        self.adapter=adapter

    def send(self,*,recipient,subject,body):
        if not self.adapter:
            return {"sent":False,"reason":"notification_adapter_not_configured"}
        return self.adapter.send(recipient=recipient,subject=subject,body=body)

    @staticmethod
    def _insert(conn,*,user_id,reservation_id,event_type,title,body,href):
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

    def notify_reservation_created(self,reservation_id):
        try:
            with db_connection() as conn:
                with conn.transaction():
                    r=conn.execute(
                        """select r.id,r.reference,r.user_id,r.organization_id,r.status,
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
                    self._insert(
                        conn,
                        user_id=r["user_id"],
                        reservation_id=r["id"],
                        event_type="reservation.created",
                        title=guest_title,
                        body=guest_body,
                        href=f"/reservation/{r['id']}",
                    )

                    members=list(conn.execute(
                        """select user_id from organization_members
                           where organization_id=%s
                             and status='active'
                             and role in ('owner','manager','reservations')""",
                        (r["organization_id"],),
                    ).fetchall())
                    hotel_title={
                        "pending_confirmation":"Reservation needs approval",
                        "held":"Payment hold created",
                        "confirmed":"New reservation",
                    }.get(r["status"],"Reservation update")
                    hotel_body=f"{r['reference']} for {r['property_name']} is {r['status'].replace('_',' ')}."
                    for member in members:
                        self._insert(
                            conn,
                            user_id=member["user_id"],
                            reservation_id=r["id"],
                            event_type="partner.reservation_created",
                            title=hotel_title,
                            body=hotel_body,
                            href="/partner#reservations",
                        )
            return {"created":1+len(members)}
        except Exception:
            return {"created":0,"error":"notification_write_failed"}

    def notify_guest_decision(self,reservation_id,status):
        try:
            with db_connection() as conn:
                with conn.transaction():
                    r=conn.execute(
                        """select r.id,r.reference,r.user_id,p.name property_name
                           from reservations r
                           join properties p on p.id=r.property_id
                           where r.id=%s""",
                        (reservation_id,),
                    ).fetchone()
                    if not r:
                        return {"created":0}
                    approved=status=="confirmed"
                    self._insert(
                        conn,
                        user_id=r["user_id"],
                        reservation_id=r["id"],
                        event_type="reservation.approved" if approved else "reservation.declined",
                        title="Reservation approved" if approved else "Reservation declined",
                        body=(
                            f"{r['property_name']} approved {r['reference']}."
                            if approved else
                            f"{r['property_name']} declined {r['reference']}."
                        ),
                        href=f"/reservation/{r['id']}",
                    )
            return {"created":1}
        except Exception:
            return {"created":0,"error":"notification_write_failed"}

    def notify_guest_status(self,reservation_id,status):
        try:
            with db_connection() as conn:
                with conn.transaction():
                    r=conn.execute(
                        """select r.id,r.reference,r.user_id,p.name property_name
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
                    self._insert(
                        conn,user_id=r["user_id"],reservation_id=r["id"],
                        event_type="reservation."+status,title=title,body=body,
                        href=f"/reservation/{r['id']}",
                    )
            return {"created":1}
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
