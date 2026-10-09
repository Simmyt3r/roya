-- Guest self-service special requests for owned reservations.
-- Extend the private reservation note ledger with an explicit origin so hotel
-- staff notes remain distinguishable from guest-submitted requests.

alter table private.reservation_notes
  add column if not exists origin text not null default 'hotel';

alter table private.reservation_notes
  drop constraint if exists reservation_notes_origin_check;

alter table private.reservation_notes
  add constraint reservation_notes_origin_check
  check(origin in ('hotel','guest'));

create index if not exists idx_reservation_notes_guest_open
  on private.reservation_notes(reservation_id,created_at desc)
  where kind='guest_request' and status='open';

create or replace function private.add_guest_reservation_request(
  p_actor_user_id uuid,
  p_reservation_id uuid,
  p_body text,
  p_idempotency_key text
)
returns table(
  note_id uuid,
  reservation_id uuid,
  body text,
  status text,
  origin text,
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
  v_note private.reservation_notes%rowtype;
  v_open_count integer;
begin
  if p_actor_user_id is null then raise exception 'FORBIDDEN'; end if;
  if char_length(trim(coalesce(p_body,'')))<1 or char_length(trim(p_body))>2000 then
    raise exception 'VALIDATION_ERROR';
  end if;
  if char_length(coalesce(p_idempotency_key,''))<8 or char_length(p_idempotency_key)>160 then
    raise exception 'IDEMPOTENCY_KEY_REQUIRED';
  end if;

  select r.*
  into v_r
  from public.reservations r
  where r.id=p_reservation_id
    and r.user_id=p_actor_user_id
  for update;

  if not found then raise exception 'FORBIDDEN'; end if;

  if v_r.status not in ('held','pending_confirmation','confirmed','checked_in') then
    raise exception 'REQUEST_NOT_ALLOWED';
  end if;

  select k.response_json
  into v_existing
  from public.idempotency_keys k
  where k.user_id=p_actor_user_id
    and k.scope='guest_reservation_request_add'
    and k.key=p_idempotency_key
    and k.expires_at>now();

  if v_existing is not null then
    return query select
      (v_existing->>'note_id')::uuid,
      (v_existing->>'reservation_id')::uuid,
      v_existing->>'body',
      v_existing->>'status',
      v_existing->>'origin',
      (v_existing->>'created_at')::timestamptz,
      true;
    return;
  end if;

  select count(*)::integer
  into v_open_count
  from private.reservation_notes rn
  where rn.reservation_id=p_reservation_id
    and rn.kind='guest_request'
    and rn.status='open';

  if v_open_count>=10 then raise exception 'TOO_MANY_OPEN_REQUESTS'; end if;

  insert into private.reservation_notes(
    reservation_id,organization_id,property_id,kind,body,status,origin,created_by
  )
  values(
    p_reservation_id,v_r.organization_id,v_r.property_id,
    'guest_request',trim(p_body),'open','guest',p_actor_user_id
  )
  returning * into v_note;

  insert into public.idempotency_keys(user_id,scope,key,response_json)
  values(
    p_actor_user_id,'guest_reservation_request_add',p_idempotency_key,
    jsonb_build_object(
      'note_id',v_note.id,
      'reservation_id',v_note.reservation_id,
      'body',v_note.body,
      'status',v_note.status,
      'origin',v_note.origin,
      'created_at',v_note.created_at
    )
  );

  insert into public.audit_logs(
    actor_user_id,organization_id,property_id,action,entity_type,entity_id,after_json
  )
  values(
    p_actor_user_id,v_r.organization_id,v_r.property_id,
    'reservation.guest_request_added','reservation',p_reservation_id::text,
    jsonb_build_object(
      'note_id',v_note.id,
      'kind','guest_request',
      'origin','guest',
      'status','open'
    )
  );

  return query select
    v_note.id,v_note.reservation_id,v_note.body,v_note.status,
    v_note.origin,v_note.created_at,false;
end;
$$;

revoke all on function private.add_guest_reservation_request(
  uuid,uuid,text,text
) from public,anon,authenticated;

comment on function private.add_guest_reservation_request(
  uuid,uuid,text,text
) is 'Server-only guest action for adding a special request to an owned active reservation.';
