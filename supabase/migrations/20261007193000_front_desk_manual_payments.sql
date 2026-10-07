-- Hotel-collected payments for front-desk reservations only.
-- This intentionally does not alter the guest/Paystack refund path.

alter table public.payment_transactions
  drop constraint if exists payment_transactions_provider_check;

alter table public.payment_transactions
  add constraint payment_transactions_provider_check
  check(provider in ('paystack','flutterwave','hotel'));

create or replace function private.record_partner_payment(
  p_actor_user_id uuid,
  p_reservation_id uuid,
  p_amount_minor bigint,
  p_method text,
  p_note text,
  p_idempotency_key text
)
returns table(
  transaction_id uuid,
  reservation_id uuid,
  provider_reference text,
  amount_minor bigint,
  amount_paid_minor bigint,
  outstanding_minor bigint,
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
  v_new_paid bigint;
  v_outstanding bigint;
  v_status text;
  v_tx_id uuid:=gen_random_uuid();
  v_reference text;
begin
  if p_actor_user_id is null then raise exception 'FORBIDDEN'; end if;
  if p_amount_minor is null or p_amount_minor<=0 then raise exception 'INVALID_AMOUNT'; end if;
  if p_method not in ('cash','pos_card','bank_transfer','other') then raise exception 'INVALID_METHOD'; end if;
  if char_length(coalesce(p_idempotency_key,''))<8 or char_length(p_idempotency_key)>160 then
    raise exception 'IDEMPOTENCY_KEY_REQUIRED';
  end if;

  select r,om.role
  into v_r,v_role
  from public.reservations r
  join public.organization_members om on om.organization_id=r.organization_id
  where r.id=p_reservation_id
    and om.user_id=p_actor_user_id
    and om.status='active'
  for update of r;

  if not found or v_role not in ('owner','manager','reservations','finance') then
    raise exception 'FORBIDDEN';
  end if;

  if v_r.source_channel<>'front_desk' then
    raise exception 'OFFLINE_PAYMENT_SOURCE_UNSUPPORTED';
  end if;

  if v_r.status not in ('confirmed','checked_in','checked_out') then
    raise exception 'RESERVATION_NOT_PAYABLE';
  end if;

  select k.response_json into v_existing
  from public.idempotency_keys k
  where k.user_id=p_actor_user_id
    and k.scope='partner_payment_record'
    and k.key=p_idempotency_key
    and k.expires_at>now();

  if v_existing is not null then
    return query select
      (v_existing->>'transaction_id')::uuid,
      (v_existing->>'reservation_id')::uuid,
      v_existing->>'provider_reference',
      (v_existing->>'amount_minor')::bigint,
      (v_existing->>'amount_paid_minor')::bigint,
      (v_existing->>'outstanding_minor')::bigint,
      v_existing->>'payment_status',
      true;
    return;
  end if;

  v_outstanding:=greatest(v_r.total_price_minor-v_r.amount_paid_minor,0);
  if v_outstanding<=0 then raise exception 'ALREADY_PAID'; end if;
  if p_amount_minor>v_outstanding then raise exception 'OVERPAYMENT'; end if;

  v_new_paid:=v_r.amount_paid_minor+p_amount_minor;
  v_outstanding:=greatest(v_r.total_price_minor-v_new_paid,0);
  v_status:=case when v_outstanding=0 then 'paid' else 'partially_paid' end;
  v_reference:='hotel_'||lower(v_r.reference)||'_'||substr(replace(v_tx_id::text,'-',''),1,10);

  insert into public.payment_transactions(
    id,reservation_id,provider,provider_reference,amount_minor,currency,
    status,method,raw_payload,paid_at
  ) values(
    v_tx_id,p_reservation_id,'hotel',v_reference,p_amount_minor,v_r.currency,
    'successful',p_method,
    jsonb_build_object('note',left(coalesce(p_note,''),500),'recorded_by',p_actor_user_id),
    now()
  );

  update public.reservations
  set amount_paid_minor=v_new_paid,
      payment_status=v_status,
      updated_at=now()
  where id=p_reservation_id;

  update public.payments
  set amount_captured_minor=v_new_paid,
      status=v_status,
      updated_at=now()
  where reservation_id=p_reservation_id;

  insert into public.idempotency_keys(user_id,scope,key,response_json)
  values(
    p_actor_user_id,'partner_payment_record',p_idempotency_key,
    jsonb_build_object(
      'transaction_id',v_tx_id,
      'reservation_id',p_reservation_id,
      'provider_reference',v_reference,
      'amount_minor',p_amount_minor,
      'amount_paid_minor',v_new_paid,
      'outstanding_minor',v_outstanding,
      'payment_status',v_status
    )
  );

  insert into public.audit_logs(
    actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
  ) values(
    p_actor_user_id,v_r.organization_id,v_r.property_id,
    'payment.hotel_recorded','reservation',p_reservation_id::text,
    jsonb_build_object(
      'transaction_id',v_tx_id,
      'amount_minor',p_amount_minor,
      'method',p_method,
      'payment_status',v_status,
      'outstanding_minor',v_outstanding
    )
  );

  return query
  select v_tx_id,p_reservation_id,v_reference,p_amount_minor,
         v_new_paid,v_outstanding,v_status,false;
end;
$$;

revoke all on function private.record_partner_payment(
  uuid,uuid,bigint,text,text,text
) from public,anon,authenticated;

comment on function private.record_partner_payment(
  uuid,uuid,bigint,text,text,text
) is 'Server-only recorder for cash/POS/bank/other payments on front-desk reservations.';
