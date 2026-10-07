-- Simple front-desk shift handover notes.
-- Kept in the private schema because this is staff-only operational context.

create table if not exists private.hotel_handover_notes(
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  property_id uuid not null references public.properties(id) on delete cascade,
  note text not null check(char_length(note) between 1 and 1000),
  priority text not null default 'normal' check(priority in ('normal','important','urgent')),
  status text not null default 'open' check(status in ('open','resolved')),
  created_by uuid references auth.users(id) on delete set null,
  resolved_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists idx_hotel_handover_open_property
  on private.hotel_handover_notes(property_id,priority,created_at desc)
  where status='open';

create index if not exists idx_hotel_handover_open_org
  on private.hotel_handover_notes(organization_id,created_at desc)
  where status='open';

create index if not exists idx_hotel_handover_created_by
  on private.hotel_handover_notes(created_by)
  where created_by is not null;

create index if not exists idx_hotel_handover_resolved_by
  on private.hotel_handover_notes(resolved_by)
  where resolved_by is not null;

alter table private.hotel_handover_notes enable row level security;
revoke all on table private.hotel_handover_notes from public,anon,authenticated;

comment on table private.hotel_handover_notes is
  'Server-only shift handover notes shared by hotel staff within an organization/property scope.';
