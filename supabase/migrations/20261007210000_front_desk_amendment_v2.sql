-- Front-desk reservation amendment v2.
-- Allows a confirmed single-item front-desk booking to change room type,
-- rate plan and room quantity as well as dates and guest details.
-- All inventory, repricing and payment-state changes remain atomic.

create or replace function private.amend_partner_reservation_v2(
  p_actor_user_id uuid,
  p_reservation_id uuid,
  p_room_type_id uuid,
  p_rate_plan_id uuid,
  p_quantity integer,
  p_check_in date,
  p_check_out date,
  p_adults integer,
  p_children integer,
  p_guest_name text,
  p_guest_email text,
  p_guest_phone text,
  p_idempotency_key text
)
returns table(
  reservation_id uuid,
  reference text,
  room_type_id uuid,
  rate_plan_id uuid,
  quantity integer,
  check_in date,
  check_out date,
  nights integer,
  total_price_minor bigint,
  net_paid_minor bigint,
  recordable_balance_minor bigint,
  payment_status text,
  idempotent boolean
)
language plpgsql
security invoker
set search_path='public','private'
as $$
declare
  v_existing jsonb;
  v_r public.reservations%rowtype;
  v_role text;
  v_item public.reservation_items%rowtype;
  v_rate public.rate_plans%rowtype;
  v_capacity_adults integer;
  v_capacity_children integer;
  v_nights integer;
  v_count integer;
  v_min_available integer;
  v_total bigint;
  v_total_refunded bigint;
  v_net_paid bigint;
  v_balance bigint;
  v_payment_status text;
  v_old_check_in date;
  v_old_check_out date;
  v_old_total bigint;
  v_old_room_type_id uuid;
  v_old_rate_plan_id uuid;
  v_old_quantity integer;
begin
  if p_actor_user_id is null then raise exception 'FORBIDDEN'; end if;
  if p_quantity<1 or p_quantity>10 then raise exception 'VALIDATION_ERROR'; end if;
  if p_check_in<current_date then raise exception 'PAST_CHECK_IN'; end if;
  if p_check_out<=p_check_in then raise exception 'VALIDATION_ERROR'; end if;
  v_nights:=p_check_out-p_check_in;
  if v_nights>90 then raise exception 'VALIDATION_ERROR'; end if;
  if p_adults<1 or p_children<0 then raise exception 'VALIDATION_ERROR'; end if;
  if char_length(trim(coalesce(p_guest_name,'')))<2 then raise exception 'VALIDATION_ERROR'; end if;
  if char_length(trim(coalesce(p_guest_phone,'')))<3 then raise exception 'VALIDATION_ERROR'; end if;
  if char_length(coalesce(p_idempotency_key,''))<8 or char_length(p_idempotency_key)>160 then
    raise exception 'IDEMPOTENCY_KEY_REQUIRED';
  end if;

  select r.*
  into v_r
  from public.reservations r
  where r.id=p_reservation_id
  for update;

  if not found then raise exception 'FORBIDDEN'; end if;

  select om.role
  into v_role
  from public.organization_members om
  where om.organization_id=v_r.organization_id
    and om.user_id=p_actor_user_id
    and om.status='active';

  if v_role is null or v_role not in ('owner','manager','reservations') then
    raise exception 'FORBIDDEN';
  end if;
  if v_r.source_channel<>'front_desk' then
    raise exception 'PARTNER_AMEND_SOURCE_UNSUPPORTED';
  end if;
  if v_r.status<>'confirmed' then
    raise exception 'RESERVATION_NOT_AMENDABLE';
  end if;

  select k.response_json
  into v_existing
  from public.idempotency_keys k
  where k.user_id=p_actor_user_id
    and k.scope='partner_reservation_amend_v2'
    and k.key=p_idempotency_key
    and k.expires_at>now();

  if v_existing is not null then
    return query select
      (v_existing->>'reservation_id')::uuid,
      v_existing->>'reference',
      (v_existing->>'room_type_id')::uuid,
      (v_existing->>'rate_plan_id')::uuid,
      (v_existing->>'quantity')::integer,
      (v_existing->>'check_in')::date,
      (v_existing->>'check_out')::date,
      (v_existing->>'nights')::integer,
      (v_existing->>'total_price_minor')::bigint,
      (v_existing->>'net_paid_minor')::bigint,
      (v_existing->>'recordable_balance_minor')::bigint,
      v_existing->>'payment_status',
      true;
    return;
  end if;

  select ri.*
  into v_item
  from public.reservation_items ri
  where ri.reservation_id=p_reservation_id
  order by ri.created_at
  limit 1
  for update;

  if not found then raise exception 'RESERVATION_ITEM_NOT_FOUND'; end if;
  if (select count(*) from public.reservation_items where reservation_id=p_reservation_id)<>1 then
    raise exception 'MULTI_ITEM_AMEND_UNSUPPORTED';
  end if;

  v_old_check_in:=v_r.check_in;
  v_old_check_out:=v_r.check_out;
  v_old_total:=v_r.total_price_minor;
  v_old_room_type_id:=v_item.room_type_id;
  v_old_rate_plan_id:=v_item.rate_plan_id;
  v_old_quantity:=v_item.quantity;

  select rt.capacity_adults,rt.capacity_children
  into v_capacity_adults,v_capacity_children
  from public.room_types rt
  where rt.id=p_room_type_id
    and rt.property_id=v_r.property_id
    and rt.status='active';

  if v_capacity_adults is null then raise exception 'ROOM_NOT_AVAILABLE'; end if;
  if p_adults>(v_capacity_adults*p_quantity) then raise exception 'CAPACITY_EXCEEDED'; end if;
  if p_children>(coalesce(v_capacity_children,0)*p_quantity) then raise exception 'CAPACITY_EXCEEDED'; end if;

  select rp.*
  into v_rate
  from public.rate_plans rp
  where rp.id=p_rate_plan_id
    and rp.room_type_id=p_room_type_id
    and rp.status='active';

  if not found or v_nights<v_rate.min_stay then raise exception 'RATE_NOT_AVAILABLE'; end if;
  if v_rate.currency<>v_r.currency then raise exception 'CURRENCY_CHANGE_UNSUPPORTED'; end if;

  -- Lock both the old allocation and the requested allocation in deterministic
  -- room/date order before releasing or reserving anything.
  perform 1
  from public.inventory_days i
  where
    (i.room_type_id=v_item.room_type_id
      and i.date>=v_r.check_in
      and i.date<v_r.check_out)
    or
    (i.room_type_id=p_room_type_id
      and i.date>=p_check_in
      and i.date<p_check_out)
  order by i.room_type_id,i.date
  for update;

  update public.inventory_days i
  set sold_inventory=greatest(0,i.sold_inventory-v_item.quantity),
      version=i.version+1,
      updated_at=now()
  where i.room_type_id=v_item.room_type_id
    and i.date>=v_r.check_in
    and i.date<v_r.check_out;

  select count(*),min(i.total_inventory-i.held_inventory-i.sold_inventory)
  into v_count,v_min_available
  from public.inventory_days i
  where i.room_type_id=p_room_type_id
    and i.date>=p_check_in
    and i.date<p_check_out
    and not i.stop_sell
    and i.min_stay<=v_nights;

  if v_count<>v_nights or coalesce(v_min_available,0)<p_quantity then
    raise exception 'BOOKING_CONFLICT';
  end if;

  if exists(
    select 1
    from public.inventory_days i
    where i.room_type_id=p_room_type_id
      and i.date=p_check_in
      and i.closed_to_arrival
  ) then
    raise exception 'RATE_NOT_AVAILABLE';
  end if;

  if exists(
    select 1
    from public.inventory_days i
    where i.room_type_id=p_room_type_id
      and i.date=p_check_out-1
      and i.closed_to_departure
  ) then
    raise exception 'RATE_NOT_AVAILABLE';
  end if;

  select sum(
           coalesce(dr.price_minor,i.price_override_minor,v_rate.base_price_minor)
           * p_quantity
         )::bigint
  into v_total
  from public.inventory_days i
  left join public.daily_rates dr
    on dr.rate_plan_id=p_rate_plan_id
   and dr.date=i.date
  where i.room_type_id=p_room_type_id
    and i.date>=p_check_in
    and i.date<p_check_out;

  if v_total is null then raise exception 'RATE_NOT_AVAILABLE'; end if;

  select coalesce(sum(rf.amount_minor),0)::bigint
  into v_total_refunded
  from public.refunds rf
  where rf.reservation_id=p_reservation_id
    and rf.status='successful';

  v_net_paid:=greatest(v_r.amount_paid_minor-v_total_refunded,0);
  if v_net_paid>v_total then raise exception 'REFUND_REQUIRED'; end if;
  v_balance:=greatest(v_total-v_net_paid,0);

  if v_balance=0 and v_net_paid>0 then
    v_payment_status:='paid';
  elsif v_net_paid>0 then
    v_payment_status:='partially_paid';
  else
    v_payment_status:='unpaid';
  end if;

  update public.inventory_days i
  set sold_inventory=i.sold_inventory+p_quantity,
      version=i.version+1,
      updated_at=now()
  where i.room_type_id=p_room_type_id
    and i.date>=p_check_in
    and i.date<p_check_out;

  update public.reservation_items ri
  set room_type_id=p_room_type_id,
      rate_plan_id=p_rate_plan_id,
      quantity=p_quantity,
      unit_price_minor=(v_total/v_nights/p_quantity),
      total_price_minor=v_total
  where ri.id=v_item.id;

  delete from public.reservation_nights
  where reservation_id=p_reservation_id;

  insert into public.reservation_nights(
    reservation_id,reservation_item_id,room_type_id,rate_plan_id,date,quantity,unit_price_minor
  )
  select
    p_reservation_id,v_item.id,p_room_type_id,p_rate_plan_id,i.date,p_quantity,
    coalesce(dr.price_minor,i.price_override_minor,v_rate.base_price_minor)
  from public.inventory_days i
  left join public.daily_rates dr
    on dr.rate_plan_id=p_rate_plan_id
   and dr.date=i.date
  where i.room_type_id=p_room_type_id
    and i.date>=p_check_in
    and i.date<p_check_out;

  update public.reservations r
  set guest_name=trim(p_guest_name),
      guest_email=lower(trim(coalesce(p_guest_email,''))),
      guest_phone=trim(p_guest_phone),
      check_in=p_check_in,
      check_out=p_check_out,
      nights=v_nights,
      adults=p_adults,
      children=p_children,
      total_price_minor=v_total,
      payment_status=v_payment_status,
      updated_at=now()
  where r.id=p_reservation_id
  returning r.* into v_r;

  update public.payments
  set status=v_payment_status,
      updated_at=now()
  where reservation_id=p_reservation_id;

  insert into public.idempotency_keys(user_id,scope,key,response_json)
  values(
    p_actor_user_id,'partner_reservation_amend_v2',p_idempotency_key,
    jsonb_build_object(
      'reservation_id',v_r.id,
      'reference',v_r.reference,
      'room_type_id',p_room_type_id,
      'rate_plan_id',p_rate_plan_id,
      'quantity',p_quantity,
      'check_in',v_r.check_in,
      'check_out',v_r.check_out,
      'nights',v_r.nights,
      'total_price_minor',v_total,
      'net_paid_minor',v_net_paid,
      'recordable_balance_minor',v_balance,
      'payment_status',v_payment_status
    )
  );

  insert into public.audit_logs(
    actor_user_id,organization_id,property_id,action,entity_type,entity_id,
    before_json,after_json
  ) values(
    p_actor_user_id,v_r.organization_id,v_r.property_id,
    'reservation.front_desk_amended_v2','reservation',v_r.id::text,
    jsonb_build_object(
      'room_type_id',v_old_room_type_id,
      'rate_plan_id',v_old_rate_plan_id,
      'quantity',v_old_quantity,
      'check_in',v_old_check_in,
      'check_out',v_old_check_out,
      'total_price_minor',v_old_total
    ),
    jsonb_build_object(
      'room_type_id',p_room_type_id,
      'rate_plan_id',p_rate_plan_id,
      'quantity',p_quantity,
      'check_in',p_check_in,
      'check_out',p_check_out,
      'nights',v_nights,
      'total_price_minor',v_total,
      'net_paid_minor',v_net_paid,
      'recordable_balance_minor',v_balance
    )
  );

  return query
  select
    v_r.id,v_r.reference,p_room_type_id,p_rate_plan_id,p_quantity,
    v_r.check_in,v_r.check_out,v_r.nights,v_total,v_net_paid,v_balance,
    v_payment_status,false;
end;
$$;

revoke all on function private.amend_partner_reservation_v2(
  uuid,uuid,uuid,uuid,integer,date,date,integer,integer,text,text,text,text
) from public,anon,authenticated;

comment on function private.amend_partner_reservation_v2(
  uuid,uuid,uuid,uuid,integer,date,date,integer,integer,text,text,text,text
) is 'Server-only atomic room/rate/quantity/date/contact amendment for confirmed single-item front-desk reservations.';
