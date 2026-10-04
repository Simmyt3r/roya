drop policy if exists reviews_guest_insert on public.reviews;

revoke insert,update,delete,truncate,references,trigger
on public.reviews
from anon,authenticated;

grant select on public.reviews to anon,authenticated;
