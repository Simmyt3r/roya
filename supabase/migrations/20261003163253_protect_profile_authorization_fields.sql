drop policy if exists profiles_self_update on public.profiles;

revoke insert,update,delete,truncate,references,trigger
on public.profiles
from anon,authenticated;

grant select on public.profiles to anon,authenticated;
