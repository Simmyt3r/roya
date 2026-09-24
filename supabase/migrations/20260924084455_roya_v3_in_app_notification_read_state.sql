alter table public.notifications
  add column if not exists read_at timestamptz;

create index if not exists idx_notifications_user_unread
  on public.notifications(user_id,created_at desc)
  where read_at is null and status='sent';
