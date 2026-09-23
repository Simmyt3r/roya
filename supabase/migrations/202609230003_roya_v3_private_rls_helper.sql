create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to anon, authenticated;

create or replace function private.is_org_member(p_org uuid)
returns boolean
language sql
stable
security definer
set search_path=public
as $$
  select exists(
    select 1
    from public.organization_members om
    where om.organization_id=p_org
      and om.user_id=(select auth.uid())
      and om.status='active'
  );
$$;
revoke all on function private.is_org_member(uuid) from public;
grant execute on function private.is_org_member(uuid) to anon, authenticated;

drop policy if exists organizations_member_select on public.organizations;
create policy organizations_member_select on public.organizations
for select using(private.is_org_member(id));

drop policy if exists organization_members_member_select on public.organization_members;
create policy organization_members_member_select on public.organization_members
for select using(private.is_org_member(organization_id));

drop policy if exists properties_public_or_member_select on public.properties;
create policy properties_public_or_member_select on public.properties
for select using((status='active' and verification_status='verified') or private.is_org_member(organization_id));

drop policy if exists property_images_public_select on public.property_images;
create policy property_images_public_select on public.property_images
for select using(
  exists(select 1 from public.properties p
         where p.id=property_id
           and ((p.status='active' and p.verification_status='verified') or private.is_org_member(p.organization_id)))
);

drop policy if exists room_types_public_select on public.room_types;
create policy room_types_public_select on public.room_types
for select using(
  exists(select 1 from public.properties p
         where p.id=property_id
           and ((p.status='active' and p.verification_status='verified') or private.is_org_member(p.organization_id)))
);

drop policy if exists rate_plans_public_select on public.rate_plans;
create policy rate_plans_public_select on public.rate_plans
for select using(
  exists(select 1
         from public.room_types rt
         join public.properties p on p.id=rt.property_id
         where rt.id=room_type_id
           and ((p.status='active' and p.verification_status='verified') or private.is_org_member(p.organization_id)))
);

drop policy if exists inventory_public_select on public.inventory_days;
create policy inventory_public_select on public.inventory_days
for select using(
  exists(select 1
         from public.room_types rt
         join public.properties p on p.id=rt.property_id
         where rt.id=room_type_id
           and ((p.status='active' and p.verification_status='verified') or private.is_org_member(p.organization_id)))
);

drop policy if exists reservations_owner_or_partner_select on public.reservations;
create policy reservations_owner_or_partner_select on public.reservations
for select using(user_id=(select auth.uid()) or private.is_org_member(organization_id));

drop policy if exists reservation_items_visible_select on public.reservation_items;
create policy reservation_items_visible_select on public.reservation_items
for select using(
  exists(select 1 from public.reservations r
         where r.id=reservation_id
           and (r.user_id=(select auth.uid()) or private.is_org_member(r.organization_id)))
);

drop policy if exists reservation_nights_visible_select on public.reservation_nights;
create policy reservation_nights_visible_select on public.reservation_nights
for select using(
  exists(select 1 from public.reservations r
         where r.id=reservation_id
           and (r.user_id=(select auth.uid()) or private.is_org_member(r.organization_id)))
);

drop policy if exists payments_visible_select on public.payments;
create policy payments_visible_select on public.payments
for select using(
  exists(select 1 from public.reservations r
         where r.id=reservation_id
           and (r.user_id=(select auth.uid()) or private.is_org_member(r.organization_id)))
);

drop policy if exists transactions_visible_select on public.payment_transactions;
create policy transactions_visible_select on public.payment_transactions
for select using(
  exists(select 1 from public.reservations r
         where r.id=reservation_id
           and (r.user_id=(select auth.uid()) or private.is_org_member(r.organization_id)))
);

drop policy if exists property_amenities_visible_select on public.property_amenities;
create policy property_amenities_visible_select on public.property_amenities
for select using(
  exists(select 1 from public.properties p
         where p.id=property_id
           and ((p.status='active' and p.verification_status='verified') or private.is_org_member(p.organization_id)))
);

drop policy if exists room_images_visible_select on public.room_images;
create policy room_images_visible_select on public.room_images
for select using(
  exists(select 1
         from public.room_types rt
         join public.properties p on p.id=rt.property_id
         where rt.id=room_type_id
           and ((p.status='active' and p.verification_status='verified') or private.is_org_member(p.organization_id)))
);

drop policy if exists physical_rooms_partner_select on public.physical_rooms;
create policy physical_rooms_partner_select on public.physical_rooms
for select using(
  exists(select 1
         from public.room_types rt
         join public.properties p on p.id=rt.property_id
         where rt.id=room_type_id and private.is_org_member(p.organization_id))
);

drop policy if exists rate_rules_visible_select on public.rate_rules;
create policy rate_rules_visible_select on public.rate_rules
for select using(
  exists(select 1
         from public.rate_plans rp
         join public.room_types rt on rt.id=rp.room_type_id
         join public.properties p on p.id=rt.property_id
         where rp.id=rate_plan_id
           and ((p.status='active' and p.verification_status='verified') or private.is_org_member(p.organization_id)))
);

drop policy if exists daily_rates_visible_select on public.daily_rates;
create policy daily_rates_visible_select on public.daily_rates
for select using(
  exists(select 1
         from public.rate_plans rp
         join public.room_types rt on rt.id=rp.room_type_id
         join public.properties p on p.id=rt.property_id
         where rp.id=rate_plan_id
           and ((p.status='active' and p.verification_status='verified') or private.is_org_member(p.organization_id)))
);

drop policy if exists refunds_visible_select on public.refunds;
create policy refunds_visible_select on public.refunds
for select using(
  exists(select 1 from public.reservations r
         where r.id=reservation_id
           and (r.user_id=(select auth.uid()) or private.is_org_member(r.organization_id)))
);

drop function if exists public.is_org_member(uuid);

alter extension pg_trgm set schema extensions;

revoke execute on function public.st_estimatedextent(text,text) from public, anon, authenticated;
revoke execute on function public.st_estimatedextent(text,text,text) from public, anon, authenticated;
revoke execute on function public.st_estimatedextent(text,text,text,boolean) from public, anon, authenticated;

drop policy if exists backend_only_webhooks on public.payment_webhook_events;
create policy backend_only_webhooks on public.payment_webhook_events
for all using(false) with check(false);

drop policy if exists backend_only_channels on public.channel_connections;
create policy backend_only_channels on public.channel_connections
for all using(false) with check(false);

drop policy if exists backend_only_channel_mappings on public.channel_room_mappings;
create policy backend_only_channel_mappings on public.channel_room_mappings
for all using(false) with check(false);

drop policy if exists backend_only_channel_logs on public.channel_sync_logs;
create policy backend_only_channel_logs on public.channel_sync_logs
for all using(false) with check(false);

drop policy if exists backend_only_notifications on public.notifications;
create policy backend_only_notifications on public.notifications
for all using(false) with check(false);

drop policy if exists backend_only_idempotency on public.idempotency_keys;
create policy backend_only_idempotency on public.idempotency_keys
for all using(false) with check(false);

drop policy if exists backend_only_audit on public.audit_logs;
create policy backend_only_audit on public.audit_logs
for all using(false) with check(false);
