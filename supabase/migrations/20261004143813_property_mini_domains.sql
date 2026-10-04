alter table public.properties
  add column if not exists mini_domain text;

update public.properties
set mini_domain=left(lower(slug),63)
where mini_domain is null;

alter table public.properties
  alter column mini_domain set not null;

alter table public.properties
  drop constraint if exists properties_mini_domain_format;

alter table public.properties
  add constraint properties_mini_domain_format
  check (
    length(mini_domain) between 2 and 63
    and mini_domain ~ '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$'
  );

create unique index if not exists uq_properties_mini_domain_lower
  on public.properties(lower(mini_domain));
