create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path=public
as $$
begin
  new.updated_at=now();
  return new;
end;
$$;

alter table public.amenities enable row level security;
alter table public.property_amenities enable row level security;
alter table public.physical_rooms enable row level security;
alter table public.rate_rules enable row level security;
alter table public.payment_webhook_events enable row level security;
alter table public.channel_connections enable row level security;
alter table public.channel_room_mappings enable row level security;
alter table public.channel_sync_logs enable row level security;
alter table public.notifications enable row level security;
alter table public.idempotency_keys enable row level security;
alter table public.audit_logs enable row level security;

drop policy if exists amenities_public_read on public.amenities;
create policy amenities_public_read on public.amenities
for select using (true);

drop policy if exists property_amenities_visible_select on public.property_amenities;
create policy property_amenities_visible_select on public.property_amenities
for select using (
  exists(
    select 1 from public.properties p
    where p.id=property_id
      and ((p.status='active' and p.verification_status='verified') or public.is_org_member(p.organization_id))
  )
);

drop policy if exists room_images_visible_select on public.room_images;
create policy room_images_visible_select on public.room_images
for select using (
  exists(
    select 1
    from public.room_types rt
    join public.properties p on p.id=rt.property_id
    where rt.id=room_type_id
      and ((p.status='active' and p.verification_status='verified') or public.is_org_member(p.organization_id))
  )
);

drop policy if exists physical_rooms_partner_select on public.physical_rooms;
create policy physical_rooms_partner_select on public.physical_rooms
for select using (
  exists(
    select 1
    from public.room_types rt
    join public.properties p on p.id=rt.property_id
    where rt.id=room_type_id and public.is_org_member(p.organization_id)
  )
);

drop policy if exists rate_rules_visible_select on public.rate_rules;
create policy rate_rules_visible_select on public.rate_rules
for select using (
  exists(
    select 1
    from public.rate_plans rp
    join public.room_types rt on rt.id=rp.room_type_id
    join public.properties p on p.id=rt.property_id
    where rp.id=rate_plan_id
      and ((p.status='active' and p.verification_status='verified') or public.is_org_member(p.organization_id))
  )
);

drop policy if exists daily_rates_visible_select on public.daily_rates;
create policy daily_rates_visible_select on public.daily_rates
for select using (
  exists(
    select 1
    from public.rate_plans rp
    join public.room_types rt on rt.id=rp.room_type_id
    join public.properties p on p.id=rt.property_id
    where rp.id=rate_plan_id
      and ((p.status='active' and p.verification_status='verified') or public.is_org_member(p.organization_id))
  )
);

drop policy if exists refunds_visible_select on public.refunds;
create policy refunds_visible_select on public.refunds
for select using (
  exists(
    select 1 from public.reservations r
    where r.id=reservation_id
      and (r.user_id=(select auth.uid()) or public.is_org_member(r.organization_id))
  )
);

drop policy if exists profiles_self_select on public.profiles;
create policy profiles_self_select on public.profiles
for select using(id=(select auth.uid()));

drop policy if exists profiles_self_update on public.profiles;
create policy profiles_self_update on public.profiles
for update using(id=(select auth.uid())) with check(id=(select auth.uid()));

drop policy if exists reservations_owner_or_partner_select on public.reservations;
create policy reservations_owner_or_partner_select on public.reservations
for select using(user_id=(select auth.uid()) or public.is_org_member(organization_id));

drop policy if exists reviews_public_select on public.reviews;
create policy reviews_public_select on public.reviews
for select using(is_visible=true or user_id=(select auth.uid()));

revoke all on function public.create_reservation(uuid,uuid,uuid,uuid,date,date,integer,integer,integer,text,text,text,text,text) from public, anon, authenticated;
revoke all on function public.cancel_reservation(uuid,uuid,text) from public, anon, authenticated;
revoke all on function public.expire_reservation_holds() from public, anon, authenticated;
revoke all on function public.record_successful_payment(text,bigint,jsonb) from public, anon, authenticated;
revoke all on function public.handle_new_auth_user() from public, anon, authenticated;
revoke all on function public.set_updated_at() from public, anon, authenticated;

grant execute on function public.is_org_member(uuid) to anon, authenticated;
