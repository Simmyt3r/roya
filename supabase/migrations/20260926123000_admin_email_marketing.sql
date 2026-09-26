-- Admin-managed reusable email templates and marketing campaign audit records.
-- Delivery itself reuses public.notifications so SMTP retries stay centralized.

create table if not exists private.email_templates (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  subject text not null,
  body text not null,
  category text not null default 'marketing'
    check (category in ('marketing','general','hotel_outreach')),
  is_active boolean not null default true,
  created_by uuid references auth.users(id) on delete set null,
  updated_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists idx_email_templates_name_ci
  on private.email_templates(lower(name));

create table if not exists private.email_campaigns (
  id uuid primary key default gen_random_uuid(),
  template_id uuid references private.email_templates(id) on delete set null,
  audience text not null
    check (audience in ('registered_all','registered_guests','registered_hotels','custom')),
  subject text not null,
  body text not null,
  requested_recipients integer not null default 0 check (requested_recipients >= 0),
  queued_recipients integer not null default 0 check (queued_recipients >= 0),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

alter table private.email_templates enable row level security;
alter table private.email_campaigns enable row level security;
revoke all on table private.email_templates from public, anon, authenticated;
revoke all on table private.email_campaigns from public, anon, authenticated;

insert into private.email_templates(name,subject,body,category)
values
  (
    'Platform announcement',
    'An update from iRoya',
    'Hello {{name}},\n\nWe have an update from iRoya.\n\n{{iroya_url}}\n\nThank you,\niRoya',
    'general'
  ),
  (
    'Hotel partner outreach',
    'Grow your hotel bookings with iRoya',
    'Hello {{name}},\n\niRoya helps independent hotels publish verified availability and manage bookings from one place.\n\nVisit {{iroya_url}} to learn more.\n\nRegards,\niRoya',
    'hotel_outreach'
  ),
  (
    'Guest promotion',
    'Discover verified stays on iRoya',
    'Hello {{name}},\n\nFind verified hotel availability and manage your reservation in one place with iRoya.\n\nExplore: {{iroya_url}}\n\nRegards,\niRoya',
    'marketing'
  )
on conflict do nothing;
