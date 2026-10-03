create index if not exists idx_reviews_property_visible_recent
  on public.reviews(property_id,created_at desc)
  where is_visible=true;

drop policy if exists reviews_guest_insert on public.reviews;
create policy reviews_guest_insert
on public.reviews
for insert
to authenticated
with check(
  user_id=(select auth.uid())
  and is_visible=true
  and exists(
    select 1
    from public.reservations r
    where r.id=reservation_id
      and r.user_id=(select auth.uid())
      and r.property_id=property_id
      and r.status='checked_out'
  )
);
