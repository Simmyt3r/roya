-- Reservation pre-arrival preparation.
-- Guest ETA/details and hotel preparation checklist stay server-only in private schema.

create table if not exists private.reservation_prearrival(
  reservation_id uuid primary key references public.reservations(id) on delete cascade,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  property_id uuid not null references public.properties(id) on delete cascade,
  eta_time time,
  arrival_details text check(arrival_details is null or char_length(arrival_details)<=1000),
  guest_updated_by uuid references auth.users(id) on delete set null,
  guest_updated_at timestamptz,
  guest_details_checked boolean not null default false,
  payment_checked boolean not null default false,
  requests_reviewed boolean not null default false,
  arrival_prepared boolean not null default false,
  staff_note text check(staff_note is null or char_length(staff_note)<=1000),
  checklist_updated_by uuid references auth.users(id) on delete set null,
  checklist_updated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_reservation_prearrival_org
  on private.reservation_prearrival(organization_id);

create index if not exists idx_reservation_prearrival_property
  on private.reservation_prearrival(property_id);

create index if not exists idx_reservation_prearrival_guest_updated_by
  on private.reservation_prearrival(guest_updated_by)
  where guest_updated_by is not null;

create index if not exists idx_reservation_prearrival_checklist_updated_by
  on private.reservation_prearrival(checklist_updated_by)
  where checklist_updated_by is not null;

alter table private.reservation_prearrival enable row level security;

drop policy if exists reservation_prearrival_no_client_access
  on private.reservation_prearrival;

create policy reservation_prearrival_no_client_access
on private.reservation_prearrival
for all
to anon,authenticated
using(false)
with check(false);

revoke all on table private.reservation_prearrival from public,anon,authenticated;

create or replace function private.upsert_guest_prearrival(
  p_actor_user_id uuid,
  p_reservation_id uuid,
  p_eta_time time,
  p_arrival_details text,
  p_idempotency_key text
)
returns table(
  reservation_id uuid,
  eta_time time,
  arrival_details text,
  guest_updated_at timestamptz,
  idempotent boolean
)
language plpgsql
security invoker
set search_path='public','private'
as $$
declare
  v_existing jsonb;
  v_r public.reservations%rowtype;
  v_row private.reservation_prearrival%rowtype;
begin
  if p_actor_user_id is null then raise exception 'FORBIDDEN'; end if;
  if p_eta_time is null then raise exception 'ETA_REQUIRED'; end if;
  if char_length(coalesce(p_arrival_details,''))>1000 then raise exception 'VALIDATION_ERROR'; end if;
  if char_length(coalesce(p_idempotency_key,''))<8 or char_length(p_idempotency_key)>160 then
    raise exception 'IDEMPOTENCY_KEY_REQUIRED';
  end if;

  select r.* into v_r
  from public.reservations r
  where r.id=p_reservation_id and r.user_id=p_actor_user_id
  for update;

  if not found then raise exception 'FORBIDDEN'; end if;
  if v_r.status not in ('held','pending_confirmation','confirmed') then
    raise exception 'PREARRIVAL_NOT_ALLOWED';
  end if;
  if v_r.check_in<current_date then raise exception 'PREARRIVAL_NOT_ALLOWED'; end if;

  select k.response_json into v_existing
  from public.idempotency_keys k
  where k.user_id=p_actor_user_id
    and k.scope='guest_prearrival_upsert'
    and k.key=p_idempotency_key
    and k.expires_at>now();

  if v_existing is not null then
    return query select
      (v_existing->>'reservation_id')::uuid,
      (v_existing->>'eta_time')::time,
      nullif(v_existing->>'arrival_details',''),
      (v_existing->>'guest_updated_at')::timestamptz,
      true;
    return;
  end if;

  insert into private.reservation_prearrival(
    reservation_id,organization_id,property_id,
    eta_time,arrival_details,guest_updated_by,guest_updated_at,updated_at
  )
  values(
    v_r.id,v_r.organization_id,v_r.property_id,
    p_eta_time,nullif(trim(coalesce(p_arrival_details,'')),''),
    p_actor_user_id,now(),now()
  )
  on conflict(reservation_id) do update set
    eta_time=excluded.eta_time,
    arrival_details=excluded.arrival_details,
    guest_updated_by=excluded.guest_updated_by,
    guest_updated_at=excluded.guest_updated_at,
    updated_at=now()
  returning * into v_row;

  insert into public.idempotency_keys(user_id,scope,key,response_json)
  values(
    p_actor_user_id,'guest_prearrival_upsert',p_idempotency_key,
    jsonb_build_object(
      'reservation_id',v_row.reservation_id,
      'eta_time',v_row.eta_time,
      'arrival_details',coalesce(v_row.arrival_details,''),
      'guest_updated_at',v_row.guest_updated_at
    )
  );

  insert into public.audit_logs(
    actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
  ) values(
    p_actor_user_id,v_r.organization_id,v_r.property_id,
    'reservation.prearrival_guest_updated','reservation',v_r.id::text,
    jsonb_build_object(
      'eta_time',v_row.eta_time,
      'has_arrival_details',v_row.arrival_details is not null
    )
  );

  return query select
    v_row.reservation_id,v_row.eta_time,v_row.arrival_details,
    v_row.guest_updated_at,false;
end;
$$;

revoke all on function private.upsert_guest_prearrival(
  uuid,uuid,time,text,text
) from public,anon,authenticated;

create or replace function private.update_partner_prearrival(
  p_actor_user_id uuid,
  p_reservation_id uuid,
  p_eta_time time,
  p_arrival_details text,
  p_guest_details_checked boolean,
  p_payment_checked boolean,
  p_requests_reviewed boolean,
  p_arrival_prepared boolean,
  p_staff_note text
)
returns table(
  reservation_id uuid,
  eta_time time,
  arrival_details text,
  guest_details_checked boolean,
  payment_checked boolean,
  requests_reviewed boolean,
  arrival_prepared boolean,
  staff_note text,
  checklist_updated_at timestamptz
)
language plpgsql
security invoker
set search_path='public','private'
as $$
declare
  v_r public.reservations%rowtype;
  v_role text;
  v_row private.reservation_prearrival%rowtype;
begin
  if p_actor_user_id is null then raise exception 'FORBIDDEN'; end if;
  if char_length(coalesce(p_arrival_details,''))>1000
     or char_length(coalesce(p_staff_note,''))>1000 then
    raise exception 'VALIDATION_ERROR';
  end if;

  select r.* into v_r
  from public.reservations r
  where r.id=p_reservation_id
  for update;

  if not found then raise exception 'FORBIDDEN'; end if;

  select om.role into v_role
  from public.organization_members om
  where om.organization_id=v_r.organization_id
    and om.user_id=p_actor_user_id
    and om.status='active';

  if v_role is null or v_role not in ('owner','manager','reservations','staff') then
    raise exception 'FORBIDDEN';
  end if;

  if v_r.status not in ('held','pending_confirmation','confirmed') then
    raise exception 'PREARRIVAL_NOT_ALLOWED';
  end if;

  insert into private.reservation_prearrival(
    reservation_id,organization_id,property_id,
    eta_time,arrival_details,
    guest_details_checked,payment_checked,requests_reviewed,arrival_prepared,
    staff_note,checklist_updated_by,checklist_updated_at,updated_at
  )
  values(
    v_r.id,v_r.organization_id,v_r.property_id,
    p_eta_time,nullif(trim(coalesce(p_arrival_details,'')),''),
    coalesce(p_guest_details_checked,false),coalesce(p_payment_checked,false),
    coalesce(p_requests_reviewed,false),coalesce(p_arrival_prepared,false),
    nullif(trim(coalesce(p_staff_note,'')),''),
    p_actor_user_id,now(),now()
  )
  on conflict(reservation_id) do update set
    eta_time=coalesce(excluded.eta_time,private.reservation_prearrival.eta_time),
    arrival_details=case
      when p_arrival_details is null then private.reservation_prearrival.arrival_details
      else excluded.arrival_details
    end,
    guest_details_checked=excluded.guest_details_checked,
    payment_checked=excluded.payment_checked,
    requests_reviewed=excluded.requests_reviewed,
    arrival_prepared=excluded.arrival_prepared,
    staff_note=excluded.staff_note,
    checklist_updated_by=excluded.checklist_updated_by,
    checklist_updated_at=excluded.checklist_updated_at,
    updated_at=now()
  returning * into v_row;

  insert into public.audit_logs(
    actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
  ) values(
    p_actor_user_id,v_r.organization_id,v_r.property_id,
    'reservation.prearrival_checklist_updated','reservation',v_r.id::text,
    jsonb_build_object(
      'guest_details_checked',v_row.guest_details_checked,
      'payment_checked',v_row.payment_checked,
      'requests_reviewed',v_row.requests_reviewed,
      'arrival_prepared',v_row.arrival_prepared,
      'eta_time',v_row.eta_time
    )
  );

  return query select
    v_row.reservation_id,v_row.eta_time,v_row.arrival_details,
    v_row.guest_details_checked,v_row.payment_checked,v_row.requests_reviewed,
    v_row.arrival_prepared,v_row.staff_note,v_row.checklist_updated_at;
end;
$$;

revoke all on function private.update_partner_prearrival(
  uuid,uuid,time,text,boolean,boolean,boolean,boolean,text
) from public,anon,authenticated;

comment on table private.reservation_prearrival is
  'Server-only guest ETA and hotel pre-arrival preparation checklist.';
