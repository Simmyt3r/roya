-- Manual refund/reversal tracking for hotel-collected front-desk payments.
-- This records money the hotel has already returned. It does not call a payment gateway.

alter table public.refunds
  add column if not exists method text;

alter table public.refunds
  drop constraint if exists refunds_method_check;

alter table public.refunds
  add constraint refunds_method_check
  check(method is null or method in ('cash','pos_card','bank_transfer','other'));

create or replace function private.record_partner_refund(
  p_actor_user_id uuid,
  p_reservation_id uuid,
  p_amount_minor bigint,
  p_method text,
  p_reason text,
  p_idempotency_key text
)
returns table(
  reservation_id uuid,
  refund_reference text,
  amount_minor bigint,
  total_refunded_minor bigint,
  net_paid_minor bigint,
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
  v_tx record;
  v_tx_refunded bigint;
  v_tx_available bigint;
  v_take bigint;
  v_remaining bigint;
  v_total_paid bigint;
  v_total_refunded bigint;
  v_net_paid bigint;
  v_status text;
  v_reference text;
  v_refund_id uuid;
  v_index integer:=0;
begin
  if p_actor_user_id is null then raise exception 'FORBIDDEN'; end if;
  if p_amount_minor is null or p_amount_minor<=0 then raise exception 'INVALID_AMOUNT'; end if;
  if p_method not in ('cash','pos_card','bank_transfer','other') then raise exception 'INVALID_METHOD'; end if;
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

  if v_role is null or v_role not in ('owner','manager','finance') then
    raise exception 'FORBIDDEN';
  end if;

  if v_r.source_channel<>'front_desk' then
    raise exception 'OFFLINE_REFUND_SOURCE_UNSUPPORTED';
  end if;

  if v_r.status not in ('confirmed','checked_in','checked_out','cancelled','no_show') then
    raise exception 'RESERVATION_NOT_REFUNDABLE';
  end if;

  select k.response_json into v_existing
  from public.idempotency_keys k
  where k.user_id=p_actor_user_id
    and k.scope='partner_refund_record'
    and k.key=p_idempotency_key
    and k.expires_at>now();

  if v_existing is not null then
    return query select
      (v_existing->>'reservation_id')::uuid,
      v_existing->>'refund_reference',
      (v_existing->>'amount_minor')::bigint,
      (v_existing->>'total_refunded_minor')::bigint,
      (v_existing->>'net_paid_minor')::bigint,
      v_existing->>'payment_status',
      true;
    return;
  end if;

  select coalesce(sum(pt.amount_minor),0)::bigint
  into v_total_paid
  from public.payment_transactions pt
  where pt.reservation_id=p_reservation_id
    and pt.provider='hotel'
    and pt.status in ('successful','partially_refunded','refunded');

  select coalesce(sum(rf.amount_minor),0)::bigint
  into v_total_refunded
  from public.refunds rf
  join public.payment_transactions pt on pt.id=rf.payment_transaction_id
  where rf.reservation_id=p_reservation_id
    and rf.status='successful'
    and pt.provider='hotel';

  if v_total_paid<=0 then raise exception 'NO_HOTEL_PAYMENT'; end if;
  if p_amount_minor>(v_total_paid-v_total_refunded) then raise exception 'OVERREFUND'; end if;

  v_remaining:=p_amount_minor;
  v_reference:='hotel_ref_'||lower(v_r.reference)||'_'||substr(replace(gen_random_uuid()::text,'-',''),1,10);

  for v_tx in
    select pt.id,pt.amount_minor,pt.currency
    from public.payment_transactions pt
    where pt.reservation_id=p_reservation_id
      and pt.provider='hotel'
      and pt.status in ('successful','partially_refunded','refunded')
    order by coalesce(pt.paid_at,pt.created_at),pt.created_at
    for update
  loop
    exit when v_remaining<=0;

    select coalesce(sum(rf.amount_minor),0)::bigint
    into v_tx_refunded
    from public.refunds rf
    where rf.payment_transaction_id=v_tx.id
      and rf.status='successful';

    v_tx_available:=greatest(v_tx.amount_minor-v_tx_refunded,0);
    if v_tx_available<=0 then
      continue;
    end if;

    v_take:=least(v_tx_available,v_remaining);
    v_refund_id:=gen_random_uuid();
    v_index:=v_index+1;

    insert into public.refunds(
      id,reservation_id,payment_transaction_id,provider_reference,
      amount_minor,currency,status,reason,method,created_by_user_id
    ) values(
      v_refund_id,p_reservation_id,v_tx.id,v_reference||'_'||v_index::text,
      v_take,v_tx.currency,'successful',
      left(coalesce(nullif(trim(p_reason),''),'Hotel refund recorded'),1000),
      p_method,p_actor_user_id
    );

    v_tx_refunded:=v_tx_refunded+v_take;
    update public.payment_transactions
    set status=case when v_tx_refunded>=amount_minor then 'refunded' else 'partially_refunded' end,
        updated_at=now()
    where id=v_tx.id;

    v_remaining:=v_remaining-v_take;
  end loop;

  if v_remaining>0 then
    raise exception 'REFUND_ALLOCATION_FAILED';
  end if;

  select coalesce(sum(rf.amount_minor),0)::bigint
  into v_total_refunded
  from public.refunds rf
  join public.payment_transactions pt on pt.id=rf.payment_transaction_id
  where rf.reservation_id=p_reservation_id
    and rf.status='successful'
    and pt.provider='hotel';

  v_net_paid:=greatest(v_total_paid-v_total_refunded,0);
  v_status:=case
    when v_total_refunded>=v_total_paid then 'refunded'
    else 'partially_refunded'
  end;

  update public.payments
  set amount_refunded_minor=v_total_refunded,
      status=v_status,
      updated_at=now()
  where reservation_id=p_reservation_id;

  update public.reservations
  set payment_status=v_status,
      updated_at=now()
  where id=p_reservation_id;

  insert into public.idempotency_keys(user_id,scope,key,response_json)
  values(
    p_actor_user_id,'partner_refund_record',p_idempotency_key,
    jsonb_build_object(
      'reservation_id',p_reservation_id,
      'refund_reference',v_reference,
      'amount_minor',p_amount_minor,
      'total_refunded_minor',v_total_refunded,
      'net_paid_minor',v_net_paid,
      'payment_status',v_status
    )
  );

  insert into public.audit_logs(
    actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
  ) values(
    p_actor_user_id,v_r.organization_id,v_r.property_id,
    'refund.hotel_recorded','reservation',p_reservation_id::text,
    jsonb_build_object(
      'refund_reference',v_reference,
      'amount_minor',p_amount_minor,
      'method',p_method,
      'total_refunded_minor',v_total_refunded,
      'net_paid_minor',v_net_paid,
      'payment_status',v_status
    )
  );

  return query
  select p_reservation_id,v_reference,p_amount_minor,v_total_refunded,
         v_net_paid,v_status,false;
end;
$$;

revoke all on function private.record_partner_refund(
  uuid,uuid,bigint,text,text,text
) from public,anon,authenticated;

comment on function private.record_partner_refund(
  uuid,uuid,bigint,text,text,text
) is 'Server-only recorder for refunds already returned by a hotel on front-desk reservations.';
