-- Harden reservation/payment RPCs against PL/pgSQL output-column name collisions.
-- Forward migration following the create_reservation qualification fix.

CREATE OR REPLACE FUNCTION public.cancel_reservation(p_reservation_id uuid, p_user_id uuid, p_reason text)
 RETURNS TABLE(reservation_id uuid, status text, payment_status text)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_r public.reservations%rowtype;
  v_n record;
begin
  select r.* into v_r
  from public.reservations r
  where r.id=p_reservation_id
    and r.user_id=p_user_id
  for update;

  if not found or v_r.status not in ('held','pending_confirmation','confirmed') then
    raise exception 'RESERVATION_NOT_CANCELLABLE';
  end if;

  for v_n in
    select rn.room_type_id,rn.date,rn.quantity
    from public.reservation_nights rn
    where rn.reservation_id=p_reservation_id
  loop
    if v_r.status='confirmed' then
      update public.inventory_days i
      set sold_inventory=greatest(0,i.sold_inventory-v_n.quantity),
          version=i.version+1,
          updated_at=now()
      where i.room_type_id=v_n.room_type_id
        and i.date=v_n.date;
    else
      update public.inventory_days i
      set held_inventory=greatest(0,i.held_inventory-v_n.quantity),
          version=i.version+1,
          updated_at=now()
      where i.room_type_id=v_n.room_type_id
        and i.date=v_n.date;
    end if;
  end loop;

  update public.reservations r
  set status='cancelled',
      cancellation_reason=left(coalesce(p_reason,'Cancelled'),1000),
      cancelled_at=now(),
      expires_at=null,
      updated_at=now()
  where r.id=p_reservation_id;

  return query
  select p_reservation_id,'cancelled'::text,v_r.payment_status;
end;
$function$


CREATE OR REPLACE FUNCTION public.partner_decide_reservation(p_reservation_id uuid, p_approve boolean, p_reason text DEFAULT NULL::text)
 RETURNS TABLE(reservation_id uuid, status text, payment_status text, confirmed_at timestamp with time zone, cancelled_at timestamp with time zone)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_r public.reservations%rowtype;
  v_n record;
  v_updated uuid;
begin
  select r.* into v_r
  from public.reservations r
  where r.id=p_reservation_id
  for update;

  if not found
     or v_r.status<>'pending_confirmation'
     or v_r.guarantee_type<>'hotel_approval' then
    raise exception 'RESERVATION_NOT_DECIDABLE';
  end if;

  if v_r.expires_at is not null and v_r.expires_at<=now() then
    raise exception 'RESERVATION_EXPIRED';
  end if;

  if p_approve then
    for v_n in
      select rn.room_type_id,rn.date,rn.quantity
      from public.reservation_nights rn
      where rn.reservation_id=p_reservation_id
      order by rn.date
    loop
      update public.inventory_days i
      set held_inventory=i.held_inventory-v_n.quantity,
          sold_inventory=i.sold_inventory+v_n.quantity,
          version=i.version+1,
          updated_at=now()
      where i.room_type_id=v_n.room_type_id
        and i.date=v_n.date
        and i.held_inventory>=v_n.quantity
      returning i.id into v_updated;

      if v_updated is null then
        raise exception 'BOOKING_CONFLICT';
      end if;
      v_updated:=null;
    end loop;

    update public.reservations r
    set status='confirmed',
        confirmed_at=coalesce(r.confirmed_at,now()),
        expires_at=null,
        updated_at=now()
    where r.id=p_reservation_id
    returning r.* into v_r;
  else
    for v_n in
      select rn.room_type_id,rn.date,rn.quantity
      from public.reservation_nights rn
      where rn.reservation_id=p_reservation_id
      order by rn.date
    loop
      update public.inventory_days i
      set held_inventory=greatest(0,i.held_inventory-v_n.quantity),
          version=i.version+1,
          updated_at=now()
      where i.room_type_id=v_n.room_type_id
        and i.date=v_n.date;
    end loop;

    update public.reservations r
    set status='cancelled',
        cancellation_reason=left(coalesce(nullif(trim(p_reason),''),'Declined by property'),1000),
        cancelled_at=now(),
        expires_at=null,
        updated_at=now()
    where r.id=p_reservation_id
    returning r.* into v_r;
  end if;

  return query
  select v_r.id,v_r.status,v_r.payment_status,v_r.confirmed_at,v_r.cancelled_at;
end;
$function$


CREATE OR REPLACE FUNCTION public.record_successful_payment(p_provider_reference text, p_amount_minor bigint, p_payload jsonb)
 RETURNS TABLE(reservation_id uuid, reservation_status text, payment_status text)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_tx public.payment_transactions%rowtype;
  v_r public.reservations%rowtype;
  v_new_paid bigint;
  v_payment_status text;
  v_n record;
begin
  select pt.* into v_tx
  from public.payment_transactions pt
  where pt.provider_reference=p_provider_reference
  for update;

  if not found then raise exception 'PAYMENT_REFERENCE_NOT_FOUND'; end if;

  select r.* into v_r
  from public.reservations r
  where r.id=v_tx.reservation_id
  for update;

  if v_tx.status='successful' then
    return query select v_r.id,v_r.status,v_r.payment_status;
    return;
  end if;

  if p_amount_minor<>v_tx.amount_minor then raise exception 'PAYMENT_AMOUNT_MISMATCH'; end if;
  if v_r.status in ('cancelled','expired','checked_out') then raise exception 'RESERVATION_NOT_PAYABLE'; end if;

  update public.payment_transactions pt
  set status='successful',
      raw_payload=p_payload,
      paid_at=now(),
      updated_at=now()
  where pt.id=v_tx.id;

  v_new_paid:=least(v_r.total_price_minor,v_r.amount_paid_minor+p_amount_minor);
  v_payment_status:=case when v_new_paid>=v_r.total_price_minor then 'paid' else 'partially_paid' end;

  if v_r.status in ('held','pending_confirmation') then
    for v_n in
      select rn.room_type_id,rn.date,rn.quantity
      from public.reservation_nights rn
      where rn.reservation_id=v_r.id
    loop
      update public.inventory_days i
      set held_inventory=greatest(0,i.held_inventory-v_n.quantity),
          sold_inventory=i.sold_inventory+v_n.quantity,
          version=i.version+1,
          updated_at=now()
      where i.room_type_id=v_n.room_type_id
        and i.date=v_n.date;
    end loop;
  end if;

  update public.reservations r
  set amount_paid_minor=v_new_paid,
      payment_status=v_payment_status,
      status='confirmed',
      confirmed_at=coalesce(r.confirmed_at,now()),
      expires_at=null,
      updated_at=now()
  where r.id=v_r.id;

  update public.payments p
  set amount_captured_minor=v_new_paid,
      status=v_payment_status,
      updated_at=now()
  where p.reservation_id=v_r.id;

  return query
  select v_r.id,'confirmed'::text,v_payment_status;
end;
$function$

