alter table public.notifications
  add column if not exists attempts integer not null default 0,
  add column if not exists next_attempt_at timestamptz not null default now(),
  add column if not exists last_error text;

create index if not exists idx_notifications_email_retry
  on public.notifications(next_attempt_at,created_at)
  where channel='email' and status='queued';
