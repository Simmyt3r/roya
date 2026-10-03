-- Harden booking/payment state transitions before public booking traffic.
-- 1. Reject past check-ins at the database boundary.
-- 2. Require every held inventory row to still exist before converting a paid hold to sold stock.
-- 3. Keep privileged RPCs unavailable through anon/authenticated Data API roles.

create or replace function public.create_reservation(
  p_user_id uuid,p_property_id uuid,p_room_type_id uuid,p_rate_plan_id uuid,
  p_check_in date,p_check_out date,p_quantity integer,p_adults integer,p_children integer,
  p_guest_name text,p_guest_email text,p_guest_phone text,p_guarantee_type text,p_idempotency_key text
)
returns table(
  reservation_id uuid,reference text,status text,payment_status text,total_price_minor bigint,
  amount_due_minor bigint,expires_at timestamptz,idempotent boolean
)
language plpgsql security definer set search_path=public as $function$
declare
  v_existing jsonb;
  v_org_id uuid;
  v_capacity integer;
  v_child_capacity integer;
  v_rate public.rate_plans%rowtype;
  v_nights integer;
  v_count integer;
  v_min_available integer;
  v_total bigint;
  v_due bigint;
  v_reservation_id uuid:=gen_random_uuid();
  v_item_id uuid:=gen_random_uuid();
  v_reference text;
  v_status text;
  v_expires timestamptz;
  v_confirmed timestamptz;
begin
  if auth.uid() is not null and auth.uid()<>p_user_id then raise exception 'FORBIDDEN'; end if;
  if p_check_in<current_date then raise exception 'PAST_CHECK_IN'; end if;
  if p_check_out<=p_check_in or p_quantity<1 then raise exception 'VALIDATION_ERROR'; end if;
  v_nights:=p_check_out-p_check_in;
  if v_nights>90 then raise exception 'VALIDATION_ERROR'; end if;

  select k.response_json into v_existing
  from public.idempotency_keys k
  where k.user_id=p_user_id
    and k.scope='reservation_create'
    and k.key=p_idempotency_key
    and k.expires_at>now();

  if v_existing is not null then
    return query select
      (v_existing->>'reservation_id')::uuid,
      v_existing->>'reference',
      v_existing->>'status',
      v_existing->>'payment_status',
      (v_existing->>'total_price_minor')::bigint,
      (v_existing->>'amount_due_minor')::bigint,
      nullif(v_existing->>'expires_at','')::timestamptz,
      true;
    return;
  end if;

  select p.organization_id into v_org_id
  from public.properties p
  where p.id=p_property_id
    and p.status='active'
    and p.verification_status='verified';

  if v_org_id is null then raise exception 'PROPERTY_NOT_AVAILABLE'; end if;

  select rt.capacity_adults,rt.capacity_children into v_capacity,v_child_capacity
  from public.room_types rt
  where rt.id=p_room_type_id
    and rt.property_id=p_property_id
    and rt.status='active';

  if v_capacity is null then raise exception 'ROOM_NOT_AVAILABLE'; end if;
  if p_adults>(v_capacity*p_quantity) then raise exception 'CAPACITY_EXCEEDED'; end if;
  if p_children>(coalesce(v_child_capacity,0)*p_quantity) then raise exception 'CAPACITY_EXCEEDED'; end if;

  select rp.* into v_rate
  from public.rate_plans rp
  where rp.id=p_rate_plan_id
    and rp.room_type_id=p_room_type_id
    and rp.status='active';

  if not found or v_rate.guarantee_type<>p_guarantee_type then raise exception 'RATE_NOT_AVAILABLE'; end if;
  if v_nights<v_rate.min_stay then raise exception 'RATE_NOT_AVAILABLE'; end if;

  perform 1
  from public.inventory_days i
  where i.room_type_id=p_room_type_id
    and i.date>=p_check_in
    and i.date<p_check_out
  order by i.date
  for update;

  select count(*),min(i.total_inventory-i.held_inventory-i.sold_inventory)
  into v_count,v_min_available
  from public.inventory_days i
  where i.room_type_id=p_room_type_id
    and i.date>=p_check_in
    and i.date<p_check_out
    and not i.stop_sell
    and i.min_stay<=v_nights;

  if v_count<>v_nights or coalesce(v_min_available,0)<p_quantity then raise exception 'BOOKING_CONFLICT'; end if;

  if exists(
    select 1 from public.inventory_days i
    where i.room_type_id=p_room_type_id and i.date=p_check_in and i.closed_to_arrival
  ) then
    raise exception 'RATE_NOT_AVAILABLE';
  end if;

  if exists(
    select 1 from public.inventory_days i
    where i.room_type_id=p_room_type_id and i.date=p_check_out-1 and i.closed_to_departure
  ) then
    raise exception 'RATE_NOT_AVAILABLE';
  end if;

  select sum(coalesce(dr.price_minor,i.price_override_minor,v_rate.base_price_minor)*p_quantity)::bigint
  into v_total
  from public.inventory_days i
  left join public.daily_rates dr
    on dr.rate_plan_id=p_rate_plan_id
   and dr.date=i.date
  where i.room_type_id=p_room_type_id
    and i.date>=p_check_in
    and i.date<p_check_out;

  if p_guarantee_type='pay_now' then
    v_due:=v_total; v_status:='held'; v_expires:=now()+interval '15 minutes';
  elsif p_guarantee_type='deposit' then
    v_due:=ceil(v_total*v_rate.deposit_percent/100.0)::bigint; v_status:='held'; v_expires:=now()+interval '15 minutes';
  elsif p_guarantee_type='pay_at_property' then
    v_due:=0; v_status:='confirmed'; v_expires:=null; v_confirmed:=now();
  else
    v_due:=0; v_status:='pending_confirmation'; v_expires:=now()+interval '2 hours';
  end if;

  v_reference:='RYA-'||upper(substr(replace(v_reservation_id::text,'-',''),1,10));

  insert into public.reservations(
    id,reference,organization_id,property_id,user_id,guest_name,guest_email,guest_phone,
    check_in,check_out,nights,adults,children,currency,total_price_minor,amount_due_minor,
    status,payment_status,guarantee_type,expires_at,confirmed_at
  ) values(
    v_reservation_id,v_reference,v_org_id,p_property_id,p_user_id,p_guest_name,p_guest_email,p_guest_phone,
    p_check_in,p_check_out,v_nights,p_adults,p_children,v_rate.currency,v_total,v_due,
    v_status,'unpaid',p_guarantee_type,v_expires,v_confirmed
  );

  insert into public.reservation_items(
    id,reservation_id,room_type_id,rate_plan_id,quantity,unit_price_minor,total_price_minor
  )
  values(
    v_item_id,v_reservation_id,p_room_type_id,p_rate_plan_id,p_quantity,
    (v_total/v_nights/p_quantity),v_total
  );

  insert into public.reservation_nights(
    reservation_id,reservation_item_id,room_type_id,rate_plan_id,date,quantity,unit_price_minor
  )
  select
    v_reservation_id,v_item_id,p_room_type_id,p_rate_plan_id,i.date,p_quantity,
    coalesce(dr.price_minor,i.price_override_minor,v_rate.base_price_minor)
  from public.inventory_days i
  left join public.daily_rates dr
    on dr.rate_plan_id=p_rate_plan_id
   and dr.date=i.date
  where i.room_type_id=p_room_type_id
    and i.date>=p_check_in
    and i.date<p_check_out;

  if v_status='confirmed' then
    update public.inventory_days i
    set sold_inventory=i.sold_inventory+p_quantity,
        version=i.version+1,
        updated_at=now()
    where i.room_type_id=p_room_type_id
      and i.date>=p_check_in
      and i.date<p_check_out;
  else
    update public.inventory_days i
    set held_inventory=i.held_inventory+p_quantity,
        version=i.version+1,
        updated_at=now()
    where i.room_type_id=p_room_type_id
      and i.date>=p_check_in
      and i.date<p_check_out;
  end if;

  insert into public.payments(reservation_id,currency,status)
  values(v_reservation_id,v_rate.currency,'unpaid');

  insert into public.idempotency_keys(user_id,scope,key,response_json)
  values(
    p_user_id,'reservation_create',p_idempotency_key,
    jsonb_build_object(
      'reservation_id',v_reservation_id,
      'reference',v_reference,
      'status',v_status,
      'payment_status','unpaid',
      'total_price_minor',v_total,
      'amount_due_minor',v_due,
      'expires_at',coalesce(v_expires::text,'')
    )
  );

  return query
  select v_reservation_id,v_reference,v_status,'unpaid'::text,v_total,v_due,v_expires,false;
end;
$function$;

create or replace function public.record_successful_payment(
  p_provider_reference text,
  p_amount_minor bigint,
  p_payload jsonb
)
returns table(
  reservation_id uuid,
  reservation_status text,
  payment_status text
)
language plpgsql security definer set search_path=public as $function$
declare
  v_tx public.payment_transactions%rowtype;
  v_r public.reservations%rowtype;
  v_new_paid bigint;
  v_payment_status text;
  v_n record;
  v_updated uuid;
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
  if v_r.status in ('cancelled','expired','checked_out','no_show') then raise exception 'RESERVATION_NOT_PAYABLE'; end if;

  if v_r.status in ('held','pending_confirmation') then
    for v_n in
      select rn.room_type_id,rn.date,rn.quantity
      from public.reservation_nights rn
      where rn.reservation_id=v_r.id
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
  end if;

  update public.payment_transactions pt
  set status='successful',
      raw_payload=p_payload,
      paid_at=now(),
      updated_at=now()
  where pt.id=v_tx.id;

  v_new_paid:=least(v_r.total_price_minor,v_r.amount_paid_minor+p_amount_minor);
  v_payment_status:=case when v_new_paid>=v_r.total_price_minor then 'paid' else 'partially_paid' end;

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
$function$;

revoke all on function public.create_reservation(
  uuid,uuid,uuid,uuid,date,date,integer,integer,integer,text,text,text,text,text
) from public, anon, authenticated;

revoke all on function public.record_successful_payment(text,bigint,jsonb)
from public, anon, authenticated;
