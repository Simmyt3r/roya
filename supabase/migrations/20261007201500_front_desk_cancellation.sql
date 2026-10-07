-- Safe cancellation for hotel-created front-desk reservations.
-- Money must be fully returned before a paid booking can release inventory.

create or replace function private.cancel_partner_reservation(
  p_actor_user_id uuid,
  p_reservation_id uuid,
  p_reason text,
  p_idempotency_key text
)
returns table(
  reservation_id uuid,
  status text,
  payment_status text,
  idempotent boolean
)
language plpgsql
set search_path='public','private'
as $$
declare
  v_existing jsonb;
  v_r public.reservations%rowtype;
  v_role text;
  v_total_refunded bigint;
  v_net_collected bigint;
  v_n record;
begin
  if p_actor_user_id is null then raise exception 'FORBIDDEN'; end if;
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
    raise exception 'PARTNER_CANCEL_SOURCE_UNSUPPORTED';
  end if;

  select k.response_json into v_existing
  from public.idempotency_keys k
  where k.user_id=p_actor_user_id
    and k.scope='partner_reservation_cancel'
    and k.key=p_idempotency_key
    and k.expires_at>now();

  if v_existing is not null then
    return query select
      (v_existing->>'reservation_id')::uuid,
      v_existing->>'status',
      v_existing->>'payment_status',
      true;
    return;
  end if;

  if v_r.status='cancelled' then
    return query select v_r.id,v_r.status,v_r.payment_status,true;
    return;
  end if;

  if v_r.status<>'confirmed' then
    raise exception 'RESERVATION_NOT_CANCELLABLE';
  end if;

  select coalesce(sum(rf.amount_minor),0)::bigint
  into v_total_refunded
  from public.refunds rf
  where rf.reservation_id=p_reservation_id
    and rf.status='successful';

  v_net_collected:=greatest(v_r.amount_paid_minor-v_total_refunded,0);
  if v_net_collected>0 then
    raise exception 'REFUND_REQUIRED';
  end if;

  for v_n in
    select rn.room_type_id,rn.date,rn.quantity
    from public.reservation_nights rn
    where rn.reservation_id=p_reservation_id
    order by rn.date
  loop
    update public.inventory_days i
    set sold_inventory=greatest(0,i.sold_inventory-v_n.quantity),
        version=i.version+1,
        updated_at=now()
    where i.room_type_id=v_n.room_type_id
      and i.date=v_n.date;
  end loop;

  update public.reservations r
  set status='cancelled',
      cancellation_reason=left(coalesce(nullif(trim(p_reason),''),'Cancelled by hotel'),1000),
      cancelled_at=now(),
      expires_at=null,
      updated_at=now()
  where r.id=p_reservation_id
  returning r.* into v_r;

  insert into public.idempotency_keys(user_id,scope,key,response_json)
  values(
    p_actor_user_id,'partner_reservation_cancel',p_idempotency_key,
    jsonb_build_object(
      'reservation_id',v_r.id,
      'status',v_r.status,
      'payment_status',v_r.payment_status
    )
  );

  insert into public.audit_logs(
    actor_user_id,organization_id,property_id,action,entity_type,entity_id,before_json,after_json
  ) values(
    p_actor_user_id,v_r.organization_id,v_r.property_id,
    'reservation.front_desk_cancelled','reservation',v_r.id::text,
    jsonb_build_object('status','confirmed'),
    jsonb_build_object(
      'status','cancelled',
      'reason',left(coalesce(nullif(trim(p_reason),''),'Cancelled by hotel'),1000)
    )
  );

  return query select v_r.id,v_r.status,v_r.payment_status,false;
end;
$$;

revoke all on function private.cancel_partner_reservation(
  uuid,uuid,text,text
) from public,anon,authenticated;

comment on function private.cancel_partner_reservation(
  uuid,uuid,text,text
) is 'Server-only cancellation for confirmed front-desk reservations after any collected money has been returned.';
