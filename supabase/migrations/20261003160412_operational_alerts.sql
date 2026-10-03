create table private.operational_alerts(
  id uuid primary key default gen_random_uuid(),
  fingerprint text not null unique,
  kind text not null,
  severity text not null check(severity in ('critical','warning')),
  title text not null,
  reference text,
  detail text not null default '',
  entity_type text,
  entity_id text,
  link text,
  status text not null default 'open' check(status in ('open','acknowledged','resolved')),
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  occurrences integer not null default 1 check(occurrences>0),
  notification_sent_at timestamptz,
  acknowledged_at timestamptz,
  acknowledged_by uuid references auth.users(id) on delete set null,
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_operational_alerts_active
  on private.operational_alerts(status,severity,last_seen_at desc)
  where status in ('open','acknowledged');

create index idx_operational_alerts_acknowledged_by
  on private.operational_alerts(acknowledged_by)
  where acknowledged_by is not null;

alter table private.operational_alerts enable row level security;

create policy operational_alerts_no_client_access
on private.operational_alerts
for all
to anon,authenticated
using (false)
with check (false);

revoke all on private.operational_alerts from public,anon,authenticated;

create unique index uq_notifications_operations_alert_recipient
  on public.notifications((payload->>'operational_alert_id'),channel,recipient)
  where event_type='operations.alert'
    and payload ? 'operational_alert_id';
