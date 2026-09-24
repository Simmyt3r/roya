-- Distinguish guest/customer accounts from hotel business accounts without
-- conflating that product role with platform admin roles or organization roles.

alter table public.profiles
  add column if not exists account_type text not null default 'guest';

alter table public.profiles
  drop constraint if exists profiles_account_type_check;

alter table public.profiles
  add constraint profiles_account_type_check
  check (account_type in ('guest','hotel'));

update public.profiles p
set account_type='hotel', updated_at=now()
where exists (
  select 1
  from public.organization_members om
  where om.user_id=p.id and om.status='active'
);

create or replace function public.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path=public
as $$
declare
  v_account_type text;
begin
  v_account_type :=
    case
      when new.raw_user_meta_data->>'account_type'='hotel' then 'hotel'
      else 'guest'
    end;

  insert into public.profiles(id,name,account_type)
  values(
    new.id,
    coalesce(new.raw_user_meta_data->>'name',''),
    v_account_type
  )
  on conflict(id) do nothing;

  return new;
end;
$$;

-- Prevent authenticated clients from self-promoting platform privileges through
-- the broad self-update policy. Server-side Postgres operations (auth.uid() is null)
-- remain able to perform managed account changes.
create or replace function public.guard_profile_privileges()
returns trigger
language plpgsql
set search_path=public
as $$
begin
  if auth.uid() is not null and auth.uid()=old.id then
    if new.platform_role is distinct from old.platform_role
       or new.status is distinct from old.status then
      raise exception 'PROFILE_PRIVILEGE_CHANGE_FORBIDDEN';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_guard_profile_privileges on public.profiles;
create trigger trg_guard_profile_privileges
before update on public.profiles
for each row execute function public.guard_profile_privileges();

create index if not exists idx_profiles_account_type
  on public.profiles(account_type,status);
