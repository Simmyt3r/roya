import json

from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.common.domains import property_subdomain_from_host
from roya.notifications.service import NotificationService
from .policy import cancellation_policy_view


RESERVATION_SOURCE_CHANNELS={"direct_booking","roya_marketplace"}


class ReservationService:
    def source_channel_for_request(self,property_id,host):
        mini_domain=property_subdomain_from_host(host)
        if not mini_domain:
            return "roya_marketplace"
        with db_connection() as conn:
            matched=conn.execute(
                """select 1
                   from properties
                   where id=%s
                     and lower(mini_domain)=lower(%s)
                     and status='active'
                     and verification_status='verified'
                   limit 1""",
                (property_id,mini_domain),
            ).fetchone()
        if not matched:
            raise RoyaError(
                "PROPERTY_HOST_MISMATCH",
                "This hotel address cannot create a reservation for another property.",
                409,
            )
        return "direct_booking"

    def create(self,user_id,payload,idempotency_key,source_channel="roya_marketplace"):
        if not idempotency_key or len(idempotency_key)>160:
            raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400)
        if source_channel not in RESERVATION_SOURCE_CHANNELS:
            raise RoyaError("VALIDATION_ERROR","Unsupported reservation source channel.",422)
        params=(user_id,str(payload.property_id),str(payload.room_type_id),str(payload.rate_plan_id),payload.check_in,payload.check_out,payload.quantity,payload.adults,payload.children,payload.guest_name,str(payload.guest_email),payload.guest_phone,payload.guarantee_type,idempotency_key)
        try:
            with db_connection() as conn:
                with conn.transaction():
                    row=conn.execute(
                        """select * from create_reservation(%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s::date,%s::date,%s::integer,%s::integer,%s::integer,%s::text,%s::text,%s::text,%s::text,%s::text)""",
                        params,
                    ).fetchone()
                    if row and not row.get("idempotent"):
                        conn.execute(
                            """update reservations
                               set source_channel=%s,updated_at=now()
                               where id=%s""",
                            (source_channel,row["reservation_id"]),
                        )
                    source_row=conn.execute(
                        "select source_channel from reservations where id=%s",
                        (row["reservation_id"],),
                    ).fetchone() if row else None
        except Exception as exc:
            message=str(exc)
            if "PAST_CHECK_IN" in message:
                raise RoyaError("VALIDATION_ERROR","Check-in cannot be in the past.",422) from exc
            if "BOOKING_CONFLICT" in message:
                raise RoyaError("BOOKING_CONFLICT","One or more selected rooms are no longer available.",409) from exc
            if "RATE_NOT_AVAILABLE" in message:
                raise RoyaError("RATE_NOT_FOUND","The selected rate is no longer available.",409) from exc
            if "CAPACITY_EXCEEDED" in message:
                raise RoyaError("VALIDATION_ERROR","Guest count exceeds the room capacity.",422) from exc
            raise
        result=dict(row) if row else row
        if result:
            result["source_channel"]=(source_row["source_channel"] if source_row else source_channel)
        if result and not result.get("idempotent"):
            NotificationService().notify_reservation_created(str(result["reservation_id"]))
        return result

    def get_for_user(self,reservation_id,user_id):
        with db_connection() as conn:
            row=conn.execute(
                """select r.*,p.name property_name,p.check_in_time,
                          rt.name room_type_name,rp.name rate_plan_name,
                          rp.refundable,rp.cancellation_policy,
                          (select rf.status from refunds rf where rf.reservation_id=r.id order by rf.created_at desc limit 1) refund_status,
                          (select rf.amount_minor from refunds rf where rf.reservation_id=r.id order by rf.created_at desc limit 1) refund_amount_minor
                   from reservations r join properties p on p.id=r.property_id
                   join reservation_items ri on ri.reservation_id=r.id
                   join room_types rt on rt.id=ri.room_type_id join rate_plans rp on rp.id=ri.rate_plan_id
                   where r.id=%s and r.user_id=%s""",(reservation_id,user_id)
            ).fetchone()
        if not row:
            raise RoyaError("NOT_FOUND","Reservation not found.",404)
        result=dict(row)
        result["cancellation_policy_view"]=cancellation_policy_view(
            refundable=bool(row["refundable"]),
            policy=row["cancellation_policy"] or {},
            check_in=row["check_in"],
            check_in_time=row["check_in_time"],
        )
        return result

    def cancel(self,reservation_id,user_id,reason):
        with db_connection() as conn:
            reservation=conn.execute(
                "select id,status,amount_paid_minor,payment_status from reservations where id=%s and user_id=%s",
                (reservation_id,user_id),
            ).fetchone()
        if not reservation:
            raise RoyaError("NOT_FOUND","Reservation not found.",404)
        if int(reservation["amount_paid_minor"] or 0)>0:
            raise RoyaError(
                "REFUND_REVIEW_REQUIRED",
                "This reservation has a recorded payment and cannot be cancelled automatically yet. Contact the property or iRoya support so the refund can be reviewed first.",
                409,
            )
        try:
            with db_connection() as conn:
                row=conn.execute(
                    "select * from cancel_reservation(%s::uuid,%s::uuid,%s::text)",
                    (reservation_id,user_id,reason or "Guest cancelled"),
                ).fetchone(); conn.commit()
        except Exception as exc:
            if "RESERVATION_NOT_CANCELLABLE" in str(exc):
                raise RoyaError("RESERVATION_NOT_CANCELLABLE","This reservation can no longer be cancelled online.",409) from exc
            raise
        return row

    def list_for_partner(self,user_id,property_id=None,limit=100):
        params=[user_id]; where=["om.user_id=%s","om.status='active'"]
        if property_id:
            where.append("r.property_id=%s"); params.append(property_id)
        params.append(limit)
        with db_connection() as conn:
            rows=list(conn.execute(
                f"""select r.id,r.reference,r.property_id,p.name property_name,r.guest_name,r.guest_email,
                           r.check_in,r.check_out,r.nights,r.total_price_minor,r.amount_paid_minor,r.currency,r.status,
                           r.payment_status,r.guarantee_type,r.source_channel,r.expires_at,r.created_at,
                           om.role member_role
                    from reservations r
                    join properties p on p.id=r.property_id
                    join organization_members om on om.organization_id=r.organization_id
                    where {' and '.join(where)}
                    order by case when r.status='pending_confirmation' then 0 else 1 end,r.created_at desc
                    limit %s""",tuple(params)
            ).fetchall())
        return rows

    def search_for_partner(self,user_id,query,property_id=None,limit=20):
        query=(query or "").strip()
        if len(query)<2:
            return []
        if len(query)>120:
            raise RoyaError("VALIDATION_ERROR","Reservation search is too long.",422)
        try:
            limit=int(limit or 20)
        except (TypeError,ValueError) as exc:
            raise RoyaError("VALIDATION_ERROR","Search result limit is invalid.",422) from exc
        limit=max(1,min(limit,50))
        needle=f"%{query}%"
        params=[user_id]
        where=["om.user_id=%s","om.status='active'"]
        if property_id:
            where.append("r.property_id::text=%s")
            params.append(str(property_id))
        params.extend([needle,needle,needle,needle,needle,needle,limit])

        with db_connection() as conn:
            rows=list(conn.execute(
                f"""select
                           r.id,r.reference,r.property_id,r.guest_name,r.guest_email,r.guest_phone,
                           r.check_in,r.check_out,r.nights,r.total_price_minor,r.amount_paid_minor,r.currency,
                           r.status,r.payment_status,r.guarantee_type,r.source_channel,r.expires_at,r.created_at,
                           p.name property_name,om.role member_role,
                           coalesce((
                             select string_agg(distinct rt.name, ', ' order by rt.name)
                             from reservation_items ri
                             join room_types rt on rt.id=ri.room_type_id
                             where ri.reservation_id=r.id
                           ),'') room_type_names
                    from reservations r
                    join properties p on p.id=r.property_id
                    join organization_members om on om.organization_id=r.organization_id
                    where {' and '.join(where)}
                      and (
                        r.reference ilike %s
                        or r.guest_name ilike %s
                        or r.guest_email ilike %s
                        or coalesce(r.guest_phone,'') ilike %s
                        or p.name ilike %s
                        or exists(
                          select 1
                          from reservation_items sri
                          join room_types srt on srt.id=sri.room_type_id
                          where sri.reservation_id=r.id
                            and srt.name ilike %s
                        )
                      )
                    order by
                      case
                        when r.status in ('confirmed','checked_in','pending_confirmation') then 0
                        else 1
                      end,
                      r.check_in desc,
                      r.created_at desc
                    limit %s""",
                tuple(params),
            ).fetchall())
        return rows


    def guest_workspace_for_partner(self,user_id,property_id=None,query=None,limit=50):
        query=(query or "").strip()
        if len(query)>120:
            raise RoyaError("VALIDATION_ERROR","Guest search is too long.",422)
        try:
            limit=max(1,min(int(limit or 50),100))
        except (TypeError,ValueError) as exc:
            raise RoyaError("VALIDATION_ERROR","Guest result limit is invalid.",422) from exc

        with db_connection() as conn:
            membership=conn.execute(
                """select 1
                   from organization_members
                   where user_id=%s and status='active'
                   limit 1""",
                (user_id,),
            ).fetchone()
            if not membership:
                raise RoyaError("FORBIDDEN","Hotel workspace access requires an active hotel membership.",403)

            properties=[
                dict(row) for row in conn.execute(
                    """select distinct p.id,p.name,p.city
                       from properties p
                       join organization_members om on om.organization_id=p.organization_id
                       where om.user_id=%s and om.status='active'
                       order by p.name""",
                    (user_id,),
                ).fetchall()
            ]

            requested_property=str(property_id or "").strip()
            selected_property=next(
                (row for row in properties if str(row["id"])==requested_property),
                None,
            ) if requested_property else None
            if requested_property and not selected_property:
                raise RoyaError("NOT_FOUND","Property not found.",404)
            selected_property_id=str(selected_property["id"]) if selected_property else None

            base_where=["om.user_id=%s","om.status='active'"]
            base_params=[user_id]
            if selected_property_id:
                base_where.append("r.property_id=%s")
                base_params.append(selected_property_id)

            active_rows=[
                dict(row) for row in conn.execute(
                    f"""select
                          r.id,r.reference,r.property_id,r.guest_name,r.guest_email,r.guest_phone,
                          r.check_in,r.check_out,r.status,r.payment_status,r.currency,r.total_price_minor,
                          p.name property_name,om.role member_role,
                          coalesce((
                            select string_agg(distinct rt.name, ', ' order by rt.name)
                            from reservation_items ri
                            join room_types rt on rt.id=ri.room_type_id
                            where ri.reservation_id=r.id
                          ),'') room_type_names
                       from reservations r
                       join properties p on p.id=r.property_id
                       join organization_members om on om.organization_id=r.organization_id
                       where {' and '.join(base_where)}
                         and (
                           r.status='checked_in'
                           or (r.status='confirmed' and r.check_in=current_date)
                         )
                       order by
                         case when r.status='checked_in' then 0 else 1 end,
                         r.check_out,r.guest_name
                       limit %s""",
                    tuple(base_params+[limit]),
                ).fetchall()
            ]

        in_house=[row for row in active_rows if row["status"]=="checked_in"]
        arrivals=[row for row in active_rows if row["status"]=="confirmed"]
        results=[]
        query_too_short=False
        if query:
            if len(query)<2:
                query_too_short=True
            else:
                results=[
                    dict(row) for row in self.search_for_partner(
                        user_id,
                        query,
                        property_id=selected_property_id,
                        limit=limit,
                    )
                ]

        return {
            "query":query,
            "query_too_short":query_too_short,
            "properties":properties,
            "selected_property_id":selected_property_id,
            "selected_property":selected_property,
            "in_house":in_house,
            "arrivals":arrivals,
            "results":results,
        }


    def workspace_for_partner(self,user_id,tab="today",property_id=None,query=None,limit=100):
        tabs={"today","upcoming","pending","in_house","completed"}
        tab=(tab or "today").strip().lower()
        if tab not in tabs:
            raise RoyaError("VALIDATION_ERROR","Unknown reservation view.",422)

        query=(query or "").strip()
        if len(query)>120:
            raise RoyaError("VALIDATION_ERROR","Reservation search is too long.",422)
        try:
            limit=max(1,min(int(limit or 100),200))
        except (TypeError,ValueError) as exc:
            raise RoyaError("VALIDATION_ERROR","Reservation result limit is invalid.",422) from exc

        with db_connection() as conn:
            membership=conn.execute(
                """select 1
                   from organization_members
                   where user_id=%s and status='active'
                   limit 1""",
                (user_id,),
            ).fetchone()
            if not membership:
                raise RoyaError("FORBIDDEN","Hotel workspace access requires an active hotel membership.",403)

            properties=[
                dict(row) for row in conn.execute(
                    """select distinct p.id,p.name,p.city
                       from properties p
                       join organization_members om on om.organization_id=p.organization_id
                       where om.user_id=%s and om.status='active'
                       order by p.name""",
                    (user_id,),
                ).fetchall()
            ]

            requested_property=str(property_id or "").strip()
            selected_property=next(
                (row for row in properties if str(row["id"])==requested_property),
                None,
            ) if requested_property else None
            if requested_property and not selected_property:
                raise RoyaError("NOT_FOUND","Property not found.",404)
            selected_property_id=str(selected_property["id"]) if selected_property else None

            base_where=["om.user_id=%s","om.status='active'"]
            base_params=[user_id]
            if selected_property_id:
                base_where.append("r.property_id=%s")
                base_params.append(selected_property_id)

            count_row=conn.execute(
                f"""select
                       count(*) filter(
                         where r.status in ('confirmed','checked_in')
                           and r.check_in<=current_date
                           and r.check_out>=current_date
                       ) today,
                       count(*) filter(
                         where r.status='confirmed'
                           and r.check_in>current_date
                       ) upcoming,
                       count(*) filter(where r.status='pending_confirmation') pending,
                       count(*) filter(where r.status='checked_in') in_house,
                       count(*) filter(where r.status in ('checked_out','cancelled','no_show')) completed
                    from reservations r
                    join organization_members om on om.organization_id=r.organization_id
                    where {' and '.join(base_where)}""",
                tuple(base_params),
            ).fetchone()

            view_where=list(base_where)
            view_params=list(base_params)
            if tab=="today":
                view_where.extend([
                    "r.status in ('confirmed','checked_in')",
                    "r.check_in<=current_date",
                    "r.check_out>=current_date",
                ])
                order_sql="r.check_in asc,r.check_out asc,r.created_at desc"
            elif tab=="upcoming":
                view_where.extend(["r.status='confirmed'","r.check_in>current_date"])
                order_sql="r.check_in asc,r.created_at desc"
            elif tab=="pending":
                view_where.append("r.status='pending_confirmation'")
                order_sql="r.expires_at asc nulls last,r.created_at asc"
            elif tab=="in_house":
                view_where.append("r.status='checked_in'")
                order_sql="r.check_out asc,r.created_at desc"
            else:
                view_where.append("r.status in ('checked_out','cancelled','no_show')")
                order_sql="r.updated_at desc,r.created_at desc"

            if query:
                needle=f"%{query}%"
                view_where.append(
                    """(
                       r.reference ilike %s
                       or r.guest_name ilike %s
                       or r.guest_email ilike %s
                       or coalesce(r.guest_phone,'') ilike %s
                       or p.name ilike %s
                       or exists(
                         select 1
                         from reservation_items sri
                         join room_types srt on srt.id=sri.room_type_id
                         where sri.reservation_id=r.id and srt.name ilike %s
                       )
                    )"""
                )
                view_params.extend([needle,needle,needle,needle,needle,needle])

            view_params.append(limit)
            reservations=[
                dict(row) for row in conn.execute(
                    f"""select
                           r.id,r.reference,r.property_id,r.guest_name,r.guest_email,r.guest_phone,
                           r.check_in,r.check_out,r.nights,r.total_price_minor,r.amount_paid_minor,r.currency,
                           r.status,r.payment_status,r.guarantee_type,r.source_channel,r.expires_at,r.created_at,
                           p.name property_name,om.role member_role,
                           coalesce((
                             select string_agg(distinct rt.name, ', ' order by rt.name)
                             from reservation_items ri
                             join room_types rt on rt.id=ri.room_type_id
                             where ri.reservation_id=r.id
                           ),'') room_type_names
                        from reservations r
                        join properties p on p.id=r.property_id
                        join organization_members om on om.organization_id=r.organization_id
                        where {' and '.join(view_where)}
                        order by {order_sql}
                        limit %s""",
                    tuple(view_params),
                ).fetchall()
            ]

        counts={key:int((count_row or {}).get(key) or 0) for key in tabs}
        return {
            "tab":tab,
            "query":query,
            "properties":properties,
            "selected_property_id":selected_property_id,
            "selected_property":selected_property,
            "counts":counts,
            "reservations":reservations,
        }


    def get_for_partner(self,reservation_id,user_id):
        with db_connection() as conn:
            reservation=conn.execute(
                """select r.*,p.name property_name,p.city property_city,p.state property_state,
                          p.check_in_time,p.check_out_time,o.name organization_name,om.role member_role
                   from reservations r
                   join properties p on p.id=r.property_id
                   join organizations o on o.id=r.organization_id
                   join organization_members om on om.organization_id=r.organization_id
                   where r.id=%s and om.user_id=%s and om.status='active'
                   limit 1""",
                (reservation_id,user_id),
            ).fetchone()
            if not reservation:
                raise RoyaError("NOT_FOUND","Reservation not found.",404)

            items=list(conn.execute(
                """select ri.id,ri.quantity,ri.unit_price_minor,ri.total_price_minor,
                          rt.name room_type_name,rp.name rate_plan_name,rp.guarantee_type
                   from reservation_items ri
                   join room_types rt on rt.id=ri.room_type_id
                   join rate_plans rp on rp.id=ri.rate_plan_id
                   where ri.reservation_id=%s
                   order by ri.created_at""",
                (reservation_id,),
            ).fetchall())

            transactions=list(conn.execute(
                """select provider,provider_reference,amount_minor,currency,status,paid_at,created_at
                   from payment_transactions
                   where reservation_id=%s
                   order by created_at desc
                   limit 20""",
                (reservation_id,),
            ).fetchall())

            refunds=list(conn.execute(
                """select amount_minor,currency,status,reason,created_at,updated_at
                   from refunds
                   where reservation_id=%s
                   order by created_at desc
                   limit 20""",
                (reservation_id,),
            ).fetchall())

            audit=list(conn.execute(
                """select action,created_at
                   from audit_logs
                   where entity_type='reservation' and entity_id=%s
                   order by created_at desc
                   limit 30""",
                (reservation_id,),
            ).fetchall())

        return {
            "reservation":dict(reservation),
            "items":[dict(row) for row in items],
            "transactions":[dict(row) for row in transactions],
            "refunds":[dict(row) for row in refunds],
            "audit":[dict(row) for row in audit],
        }


    def partner_decide(self,reservation_id,user_id,decision,reason=None):
        approve=decision=="approve"
        try:
            with db_connection() as conn:
                with conn.transaction():
                    access=conn.execute(
                        """select r.organization_id,r.property_id,r.reference,r.status,om.role
                           from reservations r join organization_members om on om.organization_id=r.organization_id
                           where r.id=%s and om.user_id=%s and om.status='active' for update of r""",
                        (reservation_id,user_id),
                    ).fetchone()
                    if not access:
                        raise RoyaError("NOT_FOUND","Reservation not found.",404)
                    if access["role"] not in {"owner","manager","reservations"}:
                        raise RoyaError("FORBIDDEN","Your organization role cannot decide this reservation.",403)
                    row=conn.execute(
                        "select * from partner_decide_reservation(%s::uuid,%s::boolean,%s::text)",
                        (reservation_id,approve,reason),
                    ).fetchone()
                    conn.execute(
                        """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                           values(%s,%s,%s,%s,'reservation',%s,%s::jsonb,%s::jsonb)""",
                        (user_id,access["organization_id"],access["property_id"],
                         "reservation.approved" if approve else "reservation.rejected",reservation_id,
                         json.dumps({"status":access["status"]}),json.dumps({"status":row["status"]},default=str)),
                    )
        except RoyaError:
            raise
        except Exception as exc:
            message=str(exc)
            if "RESERVATION_NOT_DECIDABLE" in message:
                raise RoyaError("RESERVATION_NOT_DECIDABLE","This reservation is not awaiting property approval.",409) from exc
            if "RESERVATION_EXPIRED" in message:
                raise RoyaError("RESERVATION_EXPIRED","This approval window has expired.",409) from exc
            if "BOOKING_CONFLICT" in message:
                raise RoyaError("BOOKING_CONFLICT","Held inventory is no longer available.",409) from exc
            raise
        NotificationService().notify_guest_decision(reservation_id,row["status"])
        return row


    def partner_transition(self,reservation_id,user_id,target_status):
        allowed={
            "confirmed":{"checked_in","no_show"},
            "checked_in":{"checked_out"},
        }
        with db_connection() as conn:
            with conn.transaction():
                access=conn.execute(
                    """select r.id,r.organization_id,r.property_id,r.reference,r.status,r.check_in,r.check_out,
                              om.role,current_date today
                       from reservations r
                       join organization_members om on om.organization_id=r.organization_id
                       where r.id=%s and om.user_id=%s and om.status='active'
                       for update of r""",
                    (reservation_id,user_id),
                ).fetchone()
                if not access:
                    raise RoyaError("NOT_FOUND","Reservation not found.",404)
                if access["role"] not in {"owner","manager","reservations"}:
                    raise RoyaError("FORBIDDEN","Your organization role cannot manage this stay.",403)
                if target_status not in allowed.get(access["status"],set()):
                    raise RoyaError(
                        "INVALID_RESERVATION_TRANSITION",
                        f"Reservation cannot move from {access['status']} to {target_status}.",
                        409,
                    )
                if target_status in {"checked_in","no_show"} and access["today"]<access["check_in"]:
                    raise RoyaError(
                        "STAY_NOT_STARTED",
                        "This stay cannot be checked in or marked no-show before its check-in date.",
                        409,
                    )

                if target_status=="checked_in":
                    row=conn.execute(
                        """update reservations set status='checked_in',checked_in_at=coalesce(checked_in_at,now()),
                                  updated_at=now() where id=%s returning *""",
                        (reservation_id,),
                    ).fetchone()
                elif target_status=="checked_out":
                    row=conn.execute(
                        """update reservations set status='checked_out',checked_out_at=coalesce(checked_out_at,now()),
                                  updated_at=now() where id=%s returning *""",
                        (reservation_id,),
                    ).fetchone()
                else:
                    row=conn.execute(
                        """update reservations set status='no_show',updated_at=now()
                           where id=%s returning *""",
                        (reservation_id,),
                    ).fetchone()

                conn.execute(
                    """insert into audit_logs(actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json)
                       values(%s,%s,%s,%s,'reservation',%s,%s::jsonb,%s::jsonb)""",
                    (
                        user_id,access["organization_id"],access["property_id"],
                        "reservation."+target_status,reservation_id,
                        json.dumps({"status":access["status"]}),
                        json.dumps({"status":target_status},default=str),
                    ),
                )
        NotificationService().notify_guest_status(reservation_id,target_status)
        return row
