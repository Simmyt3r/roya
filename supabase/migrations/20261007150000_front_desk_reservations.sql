-- Server-only manual/front-desk reservation creation.
-- This keeps phone, WhatsApp and walk-in bookings on the same inventory ledger
-- without making the hotel employee the guest account owner.

create or replace function private.create_partner_reservation(
  p_actor_user_id uuid,
  p_property_id uuid,
  p_room_type_id uuid,
  p_rate_plan_id uuid,
  p_check_in date,
  p_check_out date,
  p_quantity integer,
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
  status text,
  payment_status text,
  total_price_minor bigint,
  idempotent boolean
)
language plpgsql
set search_path='public','private'
as $$
declare
  v_existing jsonb;
  v_org_id uuid;
  v_role text;
  v_capacity integer;
  v_child_capacity integer;
  v_rate public.rate_plans%rowtype;
  v_nights integer;
  v_count integer;
  v_min_available integer;
  v_total bigint;
  v_reservation_id uuid:=gen_random_uuid();
  v_item_id uuid:=gen_random_uuid();
  v_reference text;
begin
  if p_actor_user_id is null then raise exception 'FORBIDDEN'; end if;
  if p_check_in<current_date then raise exception 'PAST_CHECK_IN'; end if;
  if p_check_out<=p_check_in or p_quantity<1 then raise exception 'VALIDATION_ERROR'; end if;
  v_nights:=p_check_out-p_check_in;
  if v_nights>90 then raise exception 'VALIDATION_ERROR'; end if;
  if char_length(trim(coalesce(p_guest_name,'')))<2 then raise exception 'VALIDATION_ERROR'; end if;
  if char_length(trim(coalesce(p_guest_phone,'')))<3 then raise exception 'VALIDATION_ERROR'; end if;
  if char_length(coalesce(p_idempotency_key,''))<8 or char_length(p_idempotency_key)>160 then
    raise exception 'IDEMPOTENCY_KEY_REQUIRED';
  end if;

  select p.organization_id,om.role
  into v_org_id,v_role
  from public.properties p
  join public.organization_members om on om.organization_id=p.organization_id
  where p.id=p_property_id
    and p.status='active'
    and om.user_id=p_actor_user_id
    and om.status='active';

  if v_org_id is null or v_role not in ('owner','manager','reservations') then
    raise exception 'FORBIDDEN';
  end if;

  select k.response_json into v_existing
  from public.idempotency_keys k
  where k.user_id=p_actor_user_id
    and k.scope='partner_reservation_create'
    and k.key=p_idempotency_key
    and k.expires_at>now();

  if v_existing is not null then
    return query select
      (v_existing->>'reservation_id')::uuid,
      v_existing->>'reference',
      v_existing->>'status',
      v_existing->>'payment_status',
      (v_existing->>'total_price_minor')::bigint,
      true;
    return;
  end if;

  select rt.capacity_adults,rt.capacity_children
  into v_capacity,v_child_capacity
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

  if not found or v_nights<v_rate.min_stay then raise exception 'RATE_NOT_AVAILABLE'; end if;

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
    and i.min_stay<=v_nights
    and not (i.date=p_check_in and i.closed_to_arrival)
    and not (i.date=p_check_out-1 and i.closed_to_departure);

  if v_count<>v_nights or coalesce(v_min_available,0)<p_quantity then
    raise exception 'BOOKING_CONFLICT';
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

  v_reference:='RYA-'||upper(substr(replace(v_reservation_id::text,'-',''),1,10));

  insert into public.reservations(
    id,reference,organization_id,property_id,user_id,
    guest_name,guest_email,guest_phone,
    check_in,check_out,nights,adults,children,
    currency,total_price_minor,amount_due_minor,amount_paid_minor,
    status,payment_status,guarantee_type,confirmed_at,source_channel
  ) values(
    v_reservation_id,v_reference,v_org_id,p_property_id,null,
    trim(p_guest_name),lower(trim(coalesce(p_guest_email,''))),trim(p_guest_phone),
    p_check_in,p_check_out,v_nights,p_adults,p_children,
    v_rate.currency,v_total,0,0,
    'confirmed','unpaid','pay_at_property',now(),'front_desk'
  );

  insert into public.reservation_items(
    id,reservation_id,room_type_id,rate_plan_id,quantity,unit_price_minor,total_price_minor
  ) values(
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

  update public.inventory_days i
  set sold_inventory=i.sold_inventory+p_quantity,
      version=i.version+1,
      updated_at=now()
  where i.room_type_id=p_room_type_id
    and i.date>=p_check_in
    and i.date<p_check_out;

  insert into public.payments(reservation_id,currency,status)
  values(v_reservation_id,v_rate.currency,'unpaid');

  insert into public.idempotency_keys(user_id,scope,key,response_json)
  values(
    p_actor_user_id,'partner_reservation_create',p_idempotency_key,
    jsonb_build_object(
      'reservation_id',v_reservation_id,
      'reference',v_reference,
      'status','confirmed',
      'payment_status','unpaid',
      'total_price_minor',v_total
    )
  );

  insert into public.audit_logs(
    actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
  ) values(
    p_actor_user_id,v_org_id,p_property_id,
    'reservation.front_desk_created','reservation',v_reservation_id::text,
    jsonb_build_object(
      'reference',v_reference,
      'guest_name',trim(p_guest_name),
      'room_type_id',p_room_type_id,
      'rate_plan_id',p_rate_plan_id,
      'quantity',p_quantity,
      'source_channel','front_desk'
    )
  );

  return query
  select v_reservation_id,v_reference,'confirmed'::text,'unpaid'::text,v_total,false;
end;
$$;

revoke all on function private.create_partner_reservation(
  uuid,uuid,uuid,uuid,date,date,integer,integer,integer,text,text,text,text
) from public,anon,authenticated;

comment on function private.create_partner_reservation(
  uuid,uuid,uuid,uuid,date,date,integer,integer,integer,text,text,text,text
) is 'Server-only atomic reservation creator for hotel phone, WhatsApp and walk-in bookings.';
