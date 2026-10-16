-- iRoya v1.0 fixed-window rate limiting.
-- Stored in the private schema and accessed only by the server database role.

create table if not exists private.request_rate_limits(
  scope text not null,
  subject_hash text not null,
  window_start timestamptz not null,
  request_count integer not null default 0 check(request_count>=0),
  updated_at timestamptz not null default now(),
  primary key(scope,subject_hash,window_start)
);

create index if not exists idx_request_rate_limits_window
on private.request_rate_limits(window_start);

revoke all on table private.request_rate_limits
from public, anon, authenticated, service_role;
