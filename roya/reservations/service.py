import json
from datetime import date

from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.common.domains import property_subdomain_from_host
from roya.notifications.service import NotificationService
from .policy import cancellation_policy_view


RESERVATION_SOURCE_CHANNELS={"direct_booking","roya_marketplace","front_desk"}


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

    def front_desk_booking_options(self,user_id,property_id=None,check_in=None,check_out=None):
        with db_connection() as conn:
            properties=[
                dict(row) for row in conn.execute(
                    """select p.id,p.name,p.city,p.state,p.organization_id,om.role
                       from properties p
                       join organization_members om on om.organization_id=p.organization_id
                       where om.user_id=%s
                         and om.status='active'
                         and om.role in ('owner','manager','reservations')
                         and p.status='active'
                       order by p.name""",
                    (user_id,),
                ).fetchall()
            ]

            requested=str(property_id or "").strip()
            selected=next(
                (item for item in properties if str(item["id"])==requested),
                None,
            ) if requested else (properties[0] if len(properties)==1 else None)
            if requested and not selected:
                raise RoyaError("NOT_FOUND","Property not found.",404)
            if not properties:
                raise RoyaError("FORBIDDEN","Your hotel role cannot create front-desk reservations.",403)

            options=[]
            nights=None
            if selected and check_in and check_out:
                nights=(check_out-check_in).days
                if check_in < date.today():
                    raise RoyaError("VALIDATION_ERROR","Check-in cannot be in the past.",422)
                if nights<1 or nights>90:
                    raise RoyaError("VALIDATION_ERROR","Stay must be between 1 and 90 nights.",422)

                options=[
                    dict(row) for row in conn.execute(
                        """select
                             rt.id room_type_id,rt.name room_type_name,
                             rt.capacity_adults,rt.capacity_children,
                             rp.id rate_plan_id,rp.name rate_plan_name,rp.currency,
                             rp.meal_plan,rp.refundable,rp.guarantee_type,
                             count(i.date)::integer loaded_nights,
                             min(i.total_inventory-i.held_inventory-i.sold_inventory)::integer available_rooms,
                             sum(coalesce(dr.price_minor,i.price_override_minor,rp.base_price_minor))::bigint total_price_minor
                           from room_types rt
                           join rate_plans rp on rp.room_type_id=rt.id and rp.status='active'
                           join inventory_days i on i.room_type_id=rt.id
                            and i.date>=%s and i.date<%s
                           left join daily_rates dr on dr.rate_plan_id=rp.id and dr.date=i.date
                           where rt.property_id=%s
                             and rt.status='active'
                             and rp.min_stay<=%s
                             and not i.stop_sell
                             and i.min_stay<=%s
                             and not (i.date=%s and i.closed_to_arrival)
                             and not (i.date=(%s::date-1) and i.closed_to_departure)
                           group by rt.id,rt.name,rt.capacity_adults,rt.capacity_children,
                                    rp.id,rp.name,rp.currency,rp.meal_plan,rp.refundable,
                                    rp.guarantee_type,rp.base_price_minor
                           having count(i.date)=%s
                              and min(i.total_inventory-i.held_inventory-i.sold_inventory)>0
                           order by total_price_minor,rt.name,rp.name""",
                        (
                            check_in,check_out,str(selected["id"]),
                            nights,nights,check_in,check_out,nights,
                        ),
                    ).fetchall()
                ]

        return {
            "properties":properties,
            "selected_property":selected,
            "selected_property_id":str(selected["id"]) if selected else None,
            "check_in":check_in,
            "check_out":check_out,
            "nights":nights,
            "options":options,
        }

    def create_for_partner(self,user_id,payload,idempotency_key):
        if not idempotency_key or len(idempotency_key)<8 or len(idempotency_key)>160:
            raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400)
        params=(
            user_id,
            str(payload.property_id),
            str(payload.room_type_id),
            str(payload.rate_plan_id),
            payload.check_in,
            payload.check_out,
            payload.quantity,
            payload.adults,
            payload.children,
            payload.guest_name,
            str(payload.guest_email) if payload.guest_email else "",
            payload.guest_phone,
            idempotency_key,
        )
        try:
            with db_connection() as conn:
                with conn.transaction():
                    row=conn.execute(
                        """select * from private.create_partner_reservation(
                             %s::uuid,%s::uuid,%s::uuid,%s::uuid,
                             %s::date,%s::date,%s::integer,%s::integer,%s::integer,
                             %s::text,%s::text,%s::text,%s::text
                           )""",
                        params,
                    ).fetchone()
        except Exception as exc:
            message=str(exc)
            if "FORBIDDEN" in message:
                raise RoyaError("FORBIDDEN","Your hotel role cannot create reservations.",403) from exc
            if "PAST_CHECK_IN" in message:
                raise RoyaError("VALIDATION_ERROR","Check-in cannot be in the past.",422) from exc
            if "BOOKING_CONFLICT" in message:
                raise RoyaError("BOOKING_CONFLICT","The selected room is no longer available for those dates.",409) from exc
            if "RATE_NOT_AVAILABLE" in message:
                raise RoyaError("RATE_NOT_FOUND","The selected rate is no longer available.",409) from exc
            if "ROOM_NOT_AVAILABLE" in message:
                raise RoyaError("ROOM_NOT_FOUND","The selected room type is no longer available.",409) from exc
            if "CAPACITY_EXCEEDED" in message:
                raise RoyaError("VALIDATION_ERROR","Guest count exceeds the room capacity.",422) from exc
            if "IDEMPOTENCY_KEY_REQUIRED" in message:
                raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400) from exc
            raise

        return dict(row) if row else None


    def get_for_user(self,reservation_id,user_id):
        with db_connection() as conn:
            row=conn.execute(
                """select r.*,p.name property_name,p.check_in_time,
                          rt.name room_type_name,rp.name rate_plan_name,
                          rp.refundable,rp.cancellation_policy,
                          coalesce((
                            select count(*)>0 and bool_and(
                              (select count(*) from physical_rooms pr where pr.room_type_id=ri2.room_type_id)>=rt2.total_inventory
                            )
                            from reservation_items ri2
                            join room_types rt2 on rt2.id=ri2.room_type_id
                            where ri2.reservation_id=r.id
                          ),false) room_readiness_tracked,
                          coalesce((
                            select bool_and(
                              (select count(*) from physical_rooms pr
                               where pr.room_type_id=ri2.room_type_id
                                 and pr.status='active'
                                 and pr.housekeeping_status='ready'
                                 and pr.current_reservation_id is null)>=ri2.quantity
                            )
                            from reservation_items ri2
                            where ri2.reservation_id=r.id
                          ),true) rooms_ready,
                          (select rf.status from refunds rf where rf.reservation_id=r.id order by rf.created_at desc limit 1) refund_status,
                          (select rf.amount_minor from refunds rf where rf.reservation_id=r.id order by rf.created_at desc limit 1) refund_amount_minor
                   from reservations r join properties p on p.id=r.property_id
                   join reservation_items ri on ri.reservation_id=r.id
                   join room_types rt on rt.id=ri.room_type_id join rate_plans rp on rp.id=ri.rate_plan_id
                   where r.id=%s and r.user_id=%s""",(reservation_id,user_id)
            ).fetchone()
            guest_requests=list(conn.execute(
                """select rn.id,rn.body,rn.status,rn.origin,rn.created_at,rn.resolved_at
                   from private.reservation_notes rn
                   join reservations r on r.id=rn.reservation_id
                   where rn.reservation_id=%s
                     and r.user_id=%s
                     and rn.kind='guest_request'
                   order by
                     case when rn.status='open' then 0 else 1 end,
                     rn.created_at desc
                   limit 30""",
                (reservation_id,user_id),
            ).fetchall()) if row else []
            prearrival=conn.execute(
                """select eta_time,arrival_details,guest_updated_at
                   from private.reservation_prearrival
                   where reservation_id=%s""",
                (reservation_id,),
            ).fetchone() if row else None
        if not row:
            raise RoyaError("NOT_FOUND","Reservation not found.",404)
        result=dict(row)
        result["guest_requests"]=[dict(item) for item in guest_requests]
        result["prearrival"]=dict(prearrival) if prearrival else {
            "eta_time":None,
            "arrival_details":None,
            "guest_updated_at":None,
        }
        result["cancellation_policy_view"]=cancellation_policy_view(
            refundable=bool(row["refundable"]),
            policy=row["cancellation_policy"] or {},
            check_in=row["check_in"],
            check_in_time=row["check_in_time"],
        )
        return result

    def update_guest_prearrival(self,reservation_id,user_id,payload,idempotency_key):
        if not idempotency_key or len(idempotency_key)<8 or len(idempotency_key)>160:
            raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400)
        try:
            with db_connection() as conn:
                with conn.transaction():
                    row=conn.execute(
                        """select * from private.upsert_guest_prearrival(
                             %s::uuid,%s::uuid,%s::time,%s::text,%s::text
                           )""",
                        (
                            user_id,reservation_id,payload.eta_time,
                            payload.arrival_details or "",idempotency_key,
                        ),
                    ).fetchone()
        except RoyaError:
            raise
        except Exception as exc:
            message=str(exc)
            if "ETA_REQUIRED" in message or "VALIDATION_ERROR" in message:
                raise RoyaError("VALIDATION_ERROR","Enter a valid arrival time and optional details.",422) from exc
            if "PREARRIVAL_NOT_ALLOWED" in message:
                raise RoyaError(
                    "PREARRIVAL_NOT_ALLOWED",
                    "Arrival details can only be updated before check-in.",
                    409,
                ) from exc
            if "IDEMPOTENCY_KEY_REQUIRED" in message:
                raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400) from exc
            if "FORBIDDEN" in message:
                raise RoyaError("NOT_FOUND","Reservation not found.",404) from exc
            raise
        result=dict(row) if row else None
        if result and not result.get("idempotent"):
            NotificationService().notify_prearrival_updated(reservation_id)
        return result


    def add_guest_request(self,reservation_id,user_id,body,idempotency_key):
        body=(body or "").strip()
        if not body or len(body)>2000:
            raise RoyaError("VALIDATION_ERROR","Enter a request between 1 and 2,000 characters.",422)
        if not idempotency_key or len(idempotency_key)<8 or len(idempotency_key)>160:
            raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400)

        try:
            with db_connection() as conn:
                with conn.transaction():
                    row=conn.execute(
                        """select * from private.add_guest_reservation_request(
                             %s::uuid,%s::uuid,%s::text,%s::text
                           )""",
                        (user_id,reservation_id,body,idempotency_key),
                    ).fetchone()
        except RoyaError:
            raise
        except Exception as exc:
            message=str(exc)
            if "REQUEST_NOT_ALLOWED" in message:
                raise RoyaError(
                    "REQUEST_NOT_ALLOWED",
                    "Special requests are available only before or during an active stay.",
                    409,
                ) from exc
            if "TOO_MANY_OPEN_REQUESTS" in message:
                raise RoyaError(
                    "TOO_MANY_OPEN_REQUESTS",
                    "This reservation already has several open requests. Wait for the hotel to resolve one before adding another.",
                    409,
                ) from exc
            if "VALIDATION_ERROR" in message:
                raise RoyaError("VALIDATION_ERROR","The special request is invalid.",422) from exc
            if "IDEMPOTENCY_KEY_REQUIRED" in message:
                raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400) from exc
            if "FORBIDDEN" in message:
                raise RoyaError("NOT_FOUND","Reservation not found.",404) from exc
            raise

        result=dict(row) if row else None
        if result and not result.get("idempotent"):
            NotificationService().notify_guest_request(str(result["note_id"]))
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
                    """select distinct p.id,p.name,p.city,om.role
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
                          pa.eta_time,pa.guest_details_checked,pa.payment_checked,
                          pa.requests_reviewed,pa.arrival_prepared,
                          coalesce((
                            select string_agg(distinct rt.name, ', ' order by rt.name)
                            from reservation_items ri
                            join room_types rt on rt.id=ri.room_type_id
                            where ri.reservation_id=r.id
                          ),'') room_type_names,
                          coalesce((
                            select count(*)>0 and bool_and(
                              (select count(*) from physical_rooms pr where pr.room_type_id=ri.room_type_id)>=rt.total_inventory
                            )
                            from reservation_items ri
                            join room_types rt on rt.id=ri.room_type_id
                            where ri.reservation_id=r.id
                          ),false) room_readiness_tracked,
                          coalesce((
                            select bool_and(
                              (select count(*) from physical_rooms pr
                                 where pr.room_type_id=ri.room_type_id
                                   and pr.status='active'
                                   and pr.housekeeping_status='ready'
                                   and pr.current_reservation_id is null)>=ri.quantity
                            )
                            from reservation_items ri
                            where ri.reservation_id=r.id
                          ),true) rooms_ready
                       from reservations r
                       join properties p on p.id=r.property_id
                       join organization_members om on om.organization_id=r.organization_id
                       left join private.reservation_prearrival pa on pa.reservation_id=r.id
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
        for row in arrivals:
            row["prearrival_ready"]=bool(
                row.get("guest_details_checked")
                and row.get("payment_checked")
                and row.get("requests_reviewed")
                and row.get("arrival_prepared")
                and (not row.get("room_readiness_tracked") or row.get("rooms_ready"))
            )
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
            "can_create":any(
                property.get("role") in {"owner","manager","reservations"}
                for property in properties
            ),
        }


    def get_for_partner(self,reservation_id,user_id):
        with db_connection() as conn:
            reservation=conn.execute(
                """select r.*,p.name property_name,p.address property_address,
                          p.city property_city,p.state property_state,p.country property_country,
                          p.phone property_phone,p.email property_email,
                          p.check_in_time,p.check_out_time,o.name organization_name,om.role member_role,
                          coalesce((
                            select sum(rf.amount_minor)
                            from refunds rf
                            where rf.reservation_id=r.id and rf.status='successful'
                          ),0)::bigint amount_refunded_minor
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
                """select ri.id,ri.room_type_id,ri.rate_plan_id,ri.quantity,ri.unit_price_minor,ri.total_price_minor,
                          rt.name room_type_name,rp.name rate_plan_name,rp.guarantee_type
                   from reservation_items ri
                   join room_types rt on rt.id=ri.room_type_id
                   join rate_plans rp on rp.id=ri.rate_plan_id
                   where ri.reservation_id=%s
                   order by ri.created_at""",
                (reservation_id,),
            ).fetchall())

            transactions=list(conn.execute(
                """select provider,provider_reference,amount_minor,currency,status,method,paid_at,created_at
                   from payment_transactions
                   where reservation_id=%s
                   order by created_at desc
                   limit 20""",
                (reservation_id,),
            ).fetchall())

            refunds=list(conn.execute(
                """select amount_minor,currency,status,reason,method,provider_reference,created_at,updated_at
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


            notes=list(conn.execute(
                """select
                     rn.id,rn.kind,rn.body,rn.status,rn.origin,rn.created_at,rn.resolved_at,
                     coalesce(nullif(trim(cp.name),''),cu.email,'Hotel teammate') created_by_name,
                     coalesce(nullif(trim(rp.name),''),ru.email,'Hotel teammate') resolved_by_name
                   from private.reservation_notes rn
                   left join profiles cp on cp.id=rn.created_by
                   left join auth.users cu on cu.id=rn.created_by
                   left join profiles rp on rp.id=rn.resolved_by
                   left join auth.users ru on ru.id=rn.resolved_by
                   where rn.reservation_id=%s
                   order by
                     case when rn.status='open' then 0 else 1 end,
                     rn.created_at desc
                   limit 50""",
                (reservation_id,),
            ).fetchall())

            prearrival=conn.execute(
                """select
                     eta_time,arrival_details,guest_updated_at,
                     guest_details_checked,payment_checked,requests_reviewed,arrival_prepared,
                     staff_note,checklist_updated_at
                   from private.reservation_prearrival
                   where reservation_id=%s""",
                (reservation_id,),
            ).fetchone()

            assigned_rooms=list(conn.execute(
                """select pr.id,pr.room_number,pr.floor,pr.housekeeping_status,rt.name room_type_name
                   from physical_rooms pr
                   join room_types rt on rt.id=pr.room_type_id
                   where pr.current_reservation_id=%s
                   order by rt.name,pr.room_number""",
                (reservation_id,),
            ).fetchall())

            readiness_rows=list(conn.execute(
                """select ri.room_type_id,ri.quantity,rt.name room_type_name,rt.total_inventory,
                          (select count(*) from physical_rooms pr
                             where pr.room_type_id=ri.room_type_id)::bigint configured_rooms,
                          (select count(*) from physical_rooms pr
                             where pr.room_type_id=ri.room_type_id
                               and pr.status='active'
                               and pr.housekeeping_status='ready'
                               and pr.current_reservation_id is null)::bigint ready_rooms
                   from reservation_items ri
                   join room_types rt on rt.id=ri.room_type_id
                   where ri.reservation_id=%s
                   order by ri.id""",
                (reservation_id,),
            ).fetchall())

        readiness_items=[dict(row) for row in readiness_rows]
        readiness_tracked=bool(readiness_items) and all(
            int(item["configured_rooms"] or 0)>=int(item["total_inventory"] or 0)
            for item in readiness_items
        )
        readiness_ready=(not readiness_tracked) or all(
            int(item["ready_rooms"] or 0)>=int(item["quantity"] or 0)
            for item in readiness_items
        )

        return {
            "reservation":dict(reservation),
            "items":[dict(row) for row in items],
            "transactions":[dict(row) for row in transactions],
            "refunds":[dict(row) for row in refunds],
            "notes":[dict(row) for row in notes],
            "audit":[dict(row) for row in audit],
            "assigned_rooms":[dict(row) for row in assigned_rooms],
            "room_readiness":{
                "tracked":readiness_tracked,
                "ready":readiness_ready,
                "items":readiness_items,
            },
            "prearrival":{
                **(dict(prearrival) if prearrival else {
                    "eta_time":None,
                    "arrival_details":None,
                    "guest_updated_at":None,
                    "guest_details_checked":False,
                    "payment_checked":False,
                    "requests_reviewed":False,
                    "arrival_prepared":False,
                    "staff_note":None,
                    "checklist_updated_at":None,
                }),
                "ready_to_check_in":bool(
                    readiness_ready
                    and (prearrival or {}).get("guest_details_checked",False)
                    and (prearrival or {}).get("payment_checked",False)
                    and (prearrival or {}).get("requests_reviewed",False)
                    and (prearrival or {}).get("arrival_prepared",False)
                ),
            },
        }


    def add_partner_note(self,reservation_id,user_id,kind,body,idempotency_key):
        body=(body or "").strip()
        if kind not in {"guest_request","staff_note"}:
            raise RoyaError("VALIDATION_ERROR","Choose a valid note type.",422)
        if not body or len(body)>2000:
            raise RoyaError("VALIDATION_ERROR","Enter a note between 1 and 2,000 characters.",422)
        if not idempotency_key or len(idempotency_key)<8 or len(idempotency_key)>160:
            raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400)

        try:
            with db_connection() as conn:
                with conn.transaction():
                    row=conn.execute(
                        """select * from private.add_partner_reservation_note(
                             %s::uuid,%s::uuid,%s::text,%s::text,%s::text
                           )""",
                        (user_id,reservation_id,kind,body,idempotency_key),
                    ).fetchone()
        except RoyaError:
            raise
        except Exception as exc:
            message=str(exc)
            if "INVALID_KIND" in message or "VALIDATION_ERROR" in message:
                raise RoyaError("VALIDATION_ERROR","The reservation note is invalid.",422) from exc
            if "IDEMPOTENCY_KEY_REQUIRED" in message:
                raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400) from exc
            if "FORBIDDEN" in message:
                raise RoyaError(
                    "FORBIDDEN",
                    "Your hotel role cannot add reservation notes.",
                    403,
                ) from exc
            raise
        return dict(row) if row else None


    def resolve_partner_note(self,reservation_id,note_id,user_id):
        try:
            with db_connection() as conn:
                with conn.transaction():
                    row=conn.execute(
                        """select * from private.resolve_partner_reservation_note(
                             %s::uuid,%s::uuid,%s::uuid
                           )""",
                        (user_id,reservation_id,note_id),
                    ).fetchone()
        except RoyaError:
            raise
        except Exception as exc:
            message=str(exc)
            if "NOTE_NOT_FOUND" in message:
                raise RoyaError("NOT_FOUND","Reservation note not found.",404) from exc
            if "FORBIDDEN" in message:
                raise RoyaError(
                    "FORBIDDEN",
                    "Your hotel role cannot resolve reservation notes.",
                    403,
                ) from exc
            raise
        result=dict(row) if row else None
        if result and result.get("kind")=="guest_request" and not result.get("idempotent"):
            NotificationService().notify_guest_request_resolved(str(result["note_id"]))
        return result


    def update_partner_prearrival(self,reservation_id,user_id,payload):
        try:
            with db_connection() as conn:
                with conn.transaction():
                    row=conn.execute(
                        """select * from private.update_partner_prearrival(
                             %s::uuid,%s::uuid,%s::time,%s::text,
                             %s::boolean,%s::boolean,%s::boolean,%s::boolean,%s::text
                           )""",
                        (
                            user_id,reservation_id,payload.eta_time,
                            payload.arrival_details,
                            payload.guest_details_checked,payload.payment_checked,
                            payload.requests_reviewed,payload.arrival_prepared,
                            payload.staff_note,
                        ),
                    ).fetchone()
        except RoyaError:
            raise
        except Exception as exc:
            message=str(exc)
            if "PREARRIVAL_NOT_ALLOWED" in message:
                raise RoyaError(
                    "PREARRIVAL_NOT_ALLOWED",
                    "Pre-arrival preparation is only available before check-in.",
                    409,
                ) from exc
            if "VALIDATION_ERROR" in message:
                raise RoyaError("VALIDATION_ERROR","Pre-arrival details are invalid.",422) from exc
            if "FORBIDDEN" in message:
                raise RoyaError("FORBIDDEN","Your hotel role cannot update pre-arrival preparation.",403) from exc
            raise
        return dict(row) if row else None


    def amendment_options_for_partner(self,user_id,property_id):
        with db_connection() as conn:
            rows=conn.execute(
                """select
                     rt.id room_type_id,rt.name room_type_name,
                     rt.capacity_adults,rt.capacity_children,rt.total_inventory,
                     rp.id rate_plan_id,rp.name rate_plan_name,rp.currency,
                     rp.base_price_minor,rp.min_stay,rp.meal_plan,rp.refundable,
                     rp.guarantee_type
                   from properties p
                   join organization_members om on om.organization_id=p.organization_id
                   join room_types rt on rt.property_id=p.id and rt.status='active'
                   join rate_plans rp on rp.room_type_id=rt.id and rp.status='active'
                   where p.id=%s
                     and p.status='active'
                     and om.user_id=%s
                     and om.status='active'
                     and om.role in ('owner','manager','reservations')
                   order by rt.name,rp.base_price_minor,rp.name""",
                (property_id,user_id),
            ).fetchall()
        options=[dict(row) for row in rows]
        if not options:
            raise RoyaError(
                "RATE_NOT_FOUND",
                "No active room and rate options are available for this hotel.",
                409,
            )
        return options


    def partner_amend(self,reservation_id,user_id,payload,idempotency_key):
        if not idempotency_key or len(idempotency_key)<8 or len(idempotency_key)>160:
            raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400)
        try:
            with db_connection() as conn:
                with conn.transaction():
                    row=conn.execute(
                        """select * from private.amend_partner_reservation_v2(
                             %s::uuid,%s::uuid,%s::uuid,%s::uuid,%s::integer,
                             %s::date,%s::date,%s::integer,%s::integer,
                             %s::text,%s::text,%s::text,%s::text
                           )""",
                        (
                            user_id,reservation_id,str(payload.room_type_id),str(payload.rate_plan_id),
                            payload.quantity,payload.check_in,payload.check_out,
                            payload.adults,payload.children,payload.guest_name,
                            str(payload.guest_email) if payload.guest_email else "",
                            payload.guest_phone,idempotency_key,
                        ),
                    ).fetchone()
        except RoyaError:
            raise
        except Exception as exc:
            message=str(exc)
            if "PARTNER_AMEND_SOURCE_UNSUPPORTED" in message:
                raise RoyaError(
                    "PARTNER_AMEND_SOURCE_UNSUPPORTED",
                    "Hotel-side stay changes are currently available only for front-desk reservations.",
                    409,
                ) from exc
            if "RESERVATION_NOT_AMENDABLE" in message:
                raise RoyaError(
                    "RESERVATION_NOT_AMENDABLE",
                    "Only a confirmed front-desk reservation can be changed.",
                    409,
                ) from exc
            if "MULTI_ITEM_AMEND_UNSUPPORTED" in message:
                raise RoyaError(
                    "MULTI_ITEM_AMEND_UNSUPPORTED",
                    "This reservation contains multiple room items and cannot use the simple change-stay workflow.",
                    409,
                ) from exc
            if "REFUND_REQUIRED" in message:
                raise RoyaError(
                    "REFUND_REQUIRED",
                    "The amended stay costs less than the guest's net payment. Record the required refund first.",
                    409,
                ) from exc
            if "BOOKING_CONFLICT" in message:
                raise RoyaError(
                    "BOOKING_CONFLICT",
                    "The selected room type is not available for all of the new dates.",
                    409,
                ) from exc
            if "RATE_NOT_AVAILABLE" in message:
                raise RoyaError(
                    "RATE_NOT_FOUND",
                    "The selected rate cannot be used for the amended dates.",
                    409,
                ) from exc
            if "ROOM_NOT_AVAILABLE" in message:
                raise RoyaError(
                    "ROOM_NOT_FOUND",
                    "The selected room type is no longer available for booking.",
                    409,
                ) from exc
            if "CAPACITY_EXCEEDED" in message:
                raise RoyaError("VALIDATION_ERROR","Guest count exceeds the selected room capacity.",422) from exc
            if "PAST_CHECK_IN" in message or "VALIDATION_ERROR" in message:
                raise RoyaError("VALIDATION_ERROR","The amended stay dates are invalid.",422) from exc
            if "CURRENCY_CHANGE_UNSUPPORTED" in message:
                raise RoyaError(
                    "CURRENCY_CHANGE_UNSUPPORTED",
                    "The amended rate currency must match the original reservation.",
                    409,
                ) from exc
            if "IDEMPOTENCY_KEY_REQUIRED" in message:
                raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400) from exc
            if "FORBIDDEN" in message:
                raise RoyaError("FORBIDDEN","Your hotel role cannot change this reservation.",403) from exc
            raise
        return dict(row) if row else None


    def partner_cancel(self,reservation_id,user_id,reason,idempotency_key):
        reason=(reason or "").strip()
        if len(reason)>1000:
            raise RoyaError("VALIDATION_ERROR","Cancellation reason is too long.",422)
        if not idempotency_key or len(idempotency_key)<8 or len(idempotency_key)>160:
            raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400)

        try:
            with db_connection() as conn:
                with conn.transaction():
                    row=conn.execute(
                        """select * from private.cancel_partner_reservation(
                             %s::uuid,%s::uuid,%s::text,%s::text
                           )""",
                        (user_id,reservation_id,reason,idempotency_key),
                    ).fetchone()
        except RoyaError:
            raise
        except Exception as exc:
            message=str(exc)
            if "PARTNER_CANCEL_SOURCE_UNSUPPORTED" in message:
                raise RoyaError(
                    "PARTNER_CANCEL_SOURCE_UNSUPPORTED",
                    "Hotel-side cancellation is currently available only for front-desk reservations.",
                    409,
                ) from exc
            if "REFUND_REQUIRED" in message:
                raise RoyaError(
                    "REFUND_REQUIRED",
                    "Return and record all hotel-collected money before cancelling this reservation.",
                    409,
                ) from exc
            if "RESERVATION_NOT_CANCELLABLE" in message:
                raise RoyaError(
                    "RESERVATION_NOT_CANCELLABLE",
                    "Only a confirmed front-desk reservation can be cancelled from the hotel workspace.",
                    409,
                ) from exc
            if "IDEMPOTENCY_KEY_REQUIRED" in message:
                raise RoyaError("IDEMPOTENCY_KEY_REQUIRED","A valid Idempotency-Key header is required.",400) from exc
            if "FORBIDDEN" in message:
                raise RoyaError("FORBIDDEN","Your hotel role cannot cancel this reservation.",403) from exc
            raise
        return dict(row) if row else None


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

                room_changes=[]
                if target_status=="checked_in":
                    items=list(conn.execute(
                        """select ri.room_type_id,ri.quantity,rt.name room_type_name,rt.total_inventory
                           from reservation_items ri
                           join room_types rt on rt.id=ri.room_type_id
                           where ri.reservation_id=%s
                           order by ri.id""",
                        (reservation_id,),
                    ).fetchall())

                    for item in items:
                        configured=int(conn.execute(
                            "select count(*) total from physical_rooms where room_type_id=%s",
                            (item["room_type_id"],),
                        ).fetchone()["total"] or 0)
                        if configured<int(item["total_inventory"]):
                            continue

                        ready=list(conn.execute(
                            """select id,room_number
                               from physical_rooms
                               where room_type_id=%s
                                 and status='active'
                                 and housekeeping_status='ready'
                                 and current_reservation_id is null
                               order by room_number
                               for update skip locked
                               limit %s""",
                            (item["room_type_id"],int(item["quantity"])),
                        ).fetchall())
                        if len(ready)<int(item["quantity"]):
                            raise RoyaError(
                                "ROOM_NOT_READY",
                                f"{item['room_type_name']} does not have enough ready rooms for check-in.",
                                409,
                                {
                                    "room_type":item["room_type_name"],
                                    "required":int(item["quantity"]),
                                    "ready":len(ready),
                                },
                            )

                        for physical_room in ready:
                            assigned=conn.execute(
                                """update physical_rooms
                                   set current_reservation_id=%s,assigned_at=now()
                                   where id=%s
                                   returning id,room_number""",
                                (reservation_id,physical_room["id"]),
                            ).fetchone()
                            room_changes.append({
                                "room_id":str(assigned["id"]),
                                "room_number":assigned["room_number"],
                                "change":"assigned",
                            })

                    row=conn.execute(
                        """update reservations set status='checked_in',checked_in_at=coalesce(checked_in_at,now()),
                                  updated_at=now() where id=%s returning *""",
                        (reservation_id,),
                    ).fetchone()
                elif target_status=="checked_out":
                    released=list(conn.execute(
                        """update physical_rooms
                           set current_reservation_id=null,assigned_at=null,
                               housekeeping_status='dirty',housekeeping_updated_at=now(),
                               housekeeping_updated_by=%s
                           where current_reservation_id=%s
                           returning id,room_number""",
                        (user_id,reservation_id),
                    ).fetchall())
                    room_changes=[
                        {
                            "room_id":str(physical_room["id"]),
                            "room_number":physical_room["room_number"],
                            "change":"released_dirty",
                        }
                        for physical_room in released
                    ]
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
                        json.dumps({"status":target_status,"room_changes":room_changes},default=str),
                    ),
                )
        NotificationService().notify_guest_status(reservation_id,target_status)
        return row
