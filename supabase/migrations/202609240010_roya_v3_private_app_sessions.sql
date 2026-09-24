-- Store Supabase tokens server-side behind an opaque browser session id.
-- The browser cookie contains only the random session id (Flask-signed), while
-- this private-schema table remains outside PostgREST exposure.

create table if not exists private.app_sessions(
  session_hash text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  access_token text not null,
  refresh_token text not null,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
);

create index if not exists idx_app_sessions_user_active
  on private.app_sessions(user_id,expires_at)
  where revoked_at is null;

create index if not exists idx_app_sessions_expiry
  on private.app_sessions(expires_at)
  where revoked_at is null;

revoke all on table private.app_sessions from public,anon,authenticated;
