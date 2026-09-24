create table if not exists public.organization_invites(
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  email text not null,
  role text not null check(role in ('manager','reservations','finance','staff')),
  token_hash text not null unique,
  status text not null default 'pending' check(status in ('pending','accepted','revoked','expired')),
  invited_by_user_id uuid not null references auth.users(id) on delete cascade,
  accepted_by_user_id uuid references auth.users(id) on delete set null,
  expires_at timestamptz not null,
  accepted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_organization_invites_org_status
  on public.organization_invites(organization_id,status,created_at desc);

create index if not exists idx_organization_invites_email_status
  on public.organization_invites(lower(email),status,expires_at);

alter table public.organization_invites enable row level security;

drop policy if exists backend_only_organization_invites on public.organization_invites;
create policy backend_only_organization_invites on public.organization_invites
for all using(false) with check(false);

revoke all on table public.organization_invites from anon,authenticated;
