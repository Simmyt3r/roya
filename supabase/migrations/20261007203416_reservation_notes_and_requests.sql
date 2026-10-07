-- Reservation-scoped guest requests and internal hotel notes.
-- Guest requests may be surfaced by trusted server-rendered confirmation pages.
-- Staff notes remain hotel-internal. Browser roles never query this table directly.

create table if not exists private.reservation_notes(
  id uuid primary key default gen_random_uuid(),
  reservation_id uuid not null references public.reservations(id) on delete cascade,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  property_id uuid not null references public.properties(id) on delete cascade,
  kind text not null check(kind in ('guest_request','staff_note')),
  body text not null check(char_length(body) between 1 and 2000),
  status text not null default 'open' check(status in ('open','resolved')),
  created_by uuid references auth.users(id) on delete set null,
  resolved_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  updated_at timestamptz not null default now(),
  check(
    (status='open' and resolved_at is null)
    or
    (status='resolved' and resolved_at is not null)
  )
);

create index if not exists idx_reservation_notes_reservation
  on private.reservation_notes(reservation_id,status,created_at desc);

create index if not exists idx_reservation_notes_open_property
  on private.reservation_notes(property_id,kind,created_at desc)
  where status='open';

create index if not exists idx_reservation_notes_created_by
  on private.reservation_notes(created_by)
  where created_by is not null;

create index if not exists idx_reservation_notes_resolved_by
  on private.reservation_notes(resolved_by)
  where resolved_by is not null;

alter table private.reservation_notes enable row level security;

drop policy if exists reservation_notes_no_client_access
  on private.reservation_notes;

create policy reservation_notes_no_client_access
on private.reservation_notes
for all
to anon,authenticated
using (false)
with check (false);

revoke all on table private.reservation_notes from public,anon,authenticated;

comment on table private.reservation_notes is
  'Server-only reservation guest requests and internal hotel notes.';

create or replace function private.add_partner_reservation_note(
  p_actor_user_id uuid,
  p_reservation_id uuid,
  p_kind text,
  p_body text,
  p_idempotency_key text
)
returns table(
  note_id uuid,
  reservation_id uuid,
  kind text,
  body text,
  status text,
  created_at timestamptz,
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
  v_note private.reservation_notes%rowtype;
begin
  if p_actor_user_id is null then raise exception 'FORBIDDEN'; end if;
  if p_kind not in ('guest_request','staff_note') then raise exception 'INVALID_KIND'; end if;
  if char_length(trim(coalesce(p_body,'')))<1 or char_length(trim(p_body))>2000 then
    raise exception 'VALIDATION_ERROR';
  end if;
  if char_length(coalesce(p_idempotency_key,''))<8 or char_length(p_idempotency_key)>160 then
    raise exception 'IDEMPOTENCY_KEY_REQUIRED';
  end if;

  select r.*
  into v_r
  from public.reservations r
  where r.id=p_reservation_id;

  if not found then raise exception 'FORBIDDEN'; end if;

  select om.role
  into v_role
  from public.organization_members om
  where om.organization_id=v_r.organization_id
    and om.user_id=p_actor_user_id
    and om.status='active';

  if v_role is null or v_role not in ('owner','manager','reservations','staff') then
    raise exception 'FORBIDDEN';
  end if;

  select k.response_json
  into v_existing
  from public.idempotency_keys k
  where k.user_id=p_actor_user_id
    and k.scope='partner_reservation_note_add'
    and k.key=p_idempotency_key
    and k.expires_at>now();

  if v_existing is not null then
    return query select
      (v_existing->>'note_id')::uuid,
      (v_existing->>'reservation_id')::uuid,
      v_existing->>'kind',
      v_existing->>'body',
      v_existing->>'status',
      (v_existing->>'created_at')::timestamptz,
      true;
    return;
  end if;

  insert into private.reservation_notes(
    reservation_id,organization_id,property_id,kind,body,created_by
  )
  values(
    p_reservation_id,v_r.organization_id,v_r.property_id,p_kind,trim(p_body),p_actor_user_id
  )
  returning * into v_note;

  insert into public.idempotency_keys(user_id,scope,key,response_json)
  values(
    p_actor_user_id,'partner_reservation_note_add',p_idempotency_key,
    jsonb_build_object(
      'note_id',v_note.id,
      'reservation_id',v_note.reservation_id,
      'kind',v_note.kind,
      'body',v_note.body,
      'status',v_note.status,
      'created_at',v_note.created_at
    )
  );

  insert into public.audit_logs(
    actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
  )
  values(
    p_actor_user_id,v_r.organization_id,v_r.property_id,
    'reservation.note_added','reservation',p_reservation_id::text,
    jsonb_build_object('note_id',v_note.id,'kind',v_note.kind,'status',v_note.status)
  );

  return query select
    v_note.id,v_note.reservation_id,v_note.kind,v_note.body,
    v_note.status,v_note.created_at,false;
end;
$$;

revoke all on function private.add_partner_reservation_note(
  uuid,uuid,text,text,text
) from public,anon,authenticated;

comment on function private.add_partner_reservation_note(
  uuid,uuid,text,text,text
) is 'Server-only hotel member action for guest requests and internal reservation notes.';

create or replace function private.resolve_partner_reservation_note(
  p_actor_user_id uuid,
  p_reservation_id uuid,
  p_note_id uuid
)
returns table(
  note_id uuid,
  reservation_id uuid,
  kind text,
  body text,
  status text,
  resolved_at timestamptz,
  idempotent boolean
)
language plpgsql
security invoker
set search_path='public','private'
as $$
declare
  v_r public.reservations%rowtype;
  v_role text;
  v_note private.reservation_notes%rowtype;
begin
  if p_actor_user_id is null then raise exception 'FORBIDDEN'; end if;

  select r.*
  into v_r
  from public.reservations r
  where r.id=p_reservation_id;

  if not found then raise exception 'FORBIDDEN'; end if;

  select om.role
  into v_role
  from public.organization_members om
  where om.organization_id=v_r.organization_id
    and om.user_id=p_actor_user_id
    and om.status='active';

  if v_role is null or v_role not in ('owner','manager','reservations','staff') then
    raise exception 'FORBIDDEN';
  end if;

  select rn.*
  into v_note
  from private.reservation_notes rn
  where rn.id=p_note_id
    and rn.reservation_id=p_reservation_id
    and rn.organization_id=v_r.organization_id
  for update;

  if not found then raise exception 'NOTE_NOT_FOUND'; end if;

  if v_note.status='resolved' then
    return query select
      v_note.id,v_note.reservation_id,v_note.kind,v_note.body,
      v_note.status,v_note.resolved_at,true;
    return;
  end if;

  update private.reservation_notes rn
  set status='resolved',
      resolved_by=p_actor_user_id,
      resolved_at=now(),
      updated_at=now()
  where rn.id=v_note.id
  returning * into v_note;

  insert into public.audit_logs(
    actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
  )
  values(
    p_actor_user_id,v_r.organization_id,v_r.property_id,
    'reservation.note_resolved','reservation',p_reservation_id::text,
    jsonb_build_object('note_id',v_note.id,'kind',v_note.kind,'status',v_note.status)
  );

  return query select
    v_note.id,v_note.reservation_id,v_note.kind,v_note.body,
    v_note.status,v_note.resolved_at,false;
end;
$$;

revoke all on function private.resolve_partner_reservation_note(
  uuid,uuid,uuid
) from public,anon,authenticated;

comment on function private.resolve_partner_reservation_note(
  uuid,uuid,uuid
) is 'Server-only hotel member action for resolving a reservation note or guest request.';
