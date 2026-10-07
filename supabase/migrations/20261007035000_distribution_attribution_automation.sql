alter table public.reservations
  add column if not exists source_channel text not null default 'roya_marketplace';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname='reservations_source_channel_format_check'
      and conrelid='public.reservations'::regclass
  ) then
    alter table public.reservations
      add constraint reservations_source_channel_format_check
      check (source_channel ~ '^[a-z0-9_]{2,50}$');
  end if;
end $$;

create index if not exists idx_reservations_property_source_created
  on public.reservations(property_id,source_channel,created_at desc);

create unique index if not exists uq_channel_connections_property_channel
  on public.channel_connections(property_id,channel)
  where property_id is not null;
