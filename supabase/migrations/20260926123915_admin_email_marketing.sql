-- Extend the existing consent-aware marketing email schema for the admin workspace.
-- Marketing permission remains separate from transactional reservation email.

alter table private.marketing_templates
  add column if not exists category text not null default 'marketing',
  add column if not exists is_active boolean not null default true;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname='marketing_templates_category_check'
      and conrelid='private.marketing_templates'::regclass
  ) then
    alter table private.marketing_templates
      add constraint marketing_templates_category_check
      check (category in ('marketing','general','hotel_outreach'));
  end if;
end $$;

create unique index if not exists marketing_templates_name_ci
  on private.marketing_templates(lower(name));

alter table private.marketing_campaigns
  add column if not exists template_id uuid references private.marketing_templates(id) on delete set null,
  add column if not exists requested_recipients integer not null default 0,
  add column if not exists queued_recipients integer not null default 0;

alter table private.marketing_campaigns
  drop constraint if exists marketing_campaigns_audience_check;

alter table private.marketing_campaigns
  add constraint marketing_campaigns_audience_check
  check (audience in (
    'all','registered','external',
    'registered_all','registered_guests','registered_hotels','custom'
  ));

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname='marketing_campaigns_requested_recipients_check'
      and conrelid='private.marketing_campaigns'::regclass
  ) then
    alter table private.marketing_campaigns
      add constraint marketing_campaigns_requested_recipients_check
      check (requested_recipients >= 0);
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname='marketing_campaigns_queued_recipients_check'
      and conrelid='private.marketing_campaigns'::regclass
  ) then
    alter table private.marketing_campaigns
      add constraint marketing_campaigns_queued_recipients_check
      check (queued_recipients >= 0);
  end if;
end $$;

alter table private.marketing_templates enable row level security;
alter table private.marketing_campaigns enable row level security;
alter table private.marketing_subscribers enable row level security;
revoke all on table private.marketing_templates from public, anon, authenticated;
revoke all on table private.marketing_campaigns from public, anon, authenticated;
revoke all on table private.marketing_subscribers from public, anon, authenticated;

with admin_user as (
  select id
  from public.profiles
  where platform_role='admin' and status='active'
  order by created_at asc
  limit 1
),
defaults(name,subject,body,category) as (
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
)
insert into private.marketing_templates(name,subject,body,category,created_by)
select d.name,d.subject,d.body,d.category,a.id
from defaults d cross join admin_user a
on conflict (name) do nothing;
