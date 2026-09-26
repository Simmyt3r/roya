-- Marketing permission is separate from transactional reservation email.
create table private.marketing_subscribers (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  user_id uuid unique references auth.users(id) on delete set null,
  consent_source text not null,
  consent_at timestamptz not null default now(),
  unsubscribed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint marketing_subscribers_email_check check (length(email) between 3 and 254)
);
create unique index marketing_subscribers_email_unique on private.marketing_subscribers (lower(email));
create index marketing_subscribers_active on private.marketing_subscribers (user_id) where unsubscribed_at is null;
alter table private.marketing_subscribers enable row level security;
revoke all on private.marketing_subscribers from public, anon, authenticated;

create table private.marketing_campaigns (
  id uuid primary key default gen_random_uuid(),
  subject text not null,
  body text not null,
  audience text not null check (audience in ('all','registered','external')),
  request_key uuid not null unique,
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now()
);
alter table private.marketing_campaigns enable row level security;
revoke all on private.marketing_campaigns from public, anon, authenticated;

create table private.marketing_templates (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  subject text not null,
  body text not null,
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table private.marketing_templates enable row level security;
revoke all on private.marketing_templates from public, anon, authenticated;

create unique index notifications_marketing_campaign_email_unique
  on public.notifications ((payload->>'campaign_id'),lower(recipient))
  where channel='email' and event_type='marketing.campaign';
