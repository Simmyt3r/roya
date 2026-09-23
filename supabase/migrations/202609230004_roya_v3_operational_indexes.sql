create index if not exists idx_audit_logs_actor on public.audit_logs(actor_user_id);
create index if not exists idx_audit_logs_property on public.audit_logs(property_id);

create index if not exists idx_channel_connections_org on public.channel_connections(organization_id);
create index if not exists idx_channel_connections_property on public.channel_connections(property_id);
create index if not exists idx_channel_connections_status on public.channel_connections(status,last_synced_at);

create index if not exists idx_channel_room_mappings_room on public.channel_room_mappings(room_type_id);
create index if not exists idx_channel_room_mappings_rate on public.channel_room_mappings(rate_plan_id);
create index if not exists idx_channel_sync_logs_connection on public.channel_sync_logs(connection_id,created_at desc);

create index if not exists idx_notifications_user on public.notifications(user_id,status,created_at desc);
create index if not exists idx_notifications_reservation on public.notifications(reservation_id);
create index if not exists idx_notifications_queue on public.notifications(status,created_at) where status='queued';

create index if not exists idx_properties_creator on public.properties(created_by_user_id);
create index if not exists idx_property_amenities_amenity on public.property_amenities(amenity_id);
create index if not exists idx_property_images_property on public.property_images(property_id,sort_order);

create index if not exists idx_rate_rules_plan on public.rate_rules(rate_plan_id);

create index if not exists idx_refunds_creator on public.refunds(created_by_user_id);
create index if not exists idx_refunds_transaction on public.refunds(payment_transaction_id);
create index if not exists idx_refunds_reservation on public.refunds(reservation_id,status);

create index if not exists idx_reservation_items_reservation on public.reservation_items(reservation_id);
create index if not exists idx_reservation_items_room on public.reservation_items(room_type_id);
create index if not exists idx_reservation_items_rate on public.reservation_items(rate_plan_id);
create index if not exists idx_reservation_nights_reservation on public.reservation_nights(reservation_id);
create index if not exists idx_reservation_nights_rate on public.reservation_nights(rate_plan_id);

create index if not exists idx_reservations_org on public.reservations(organization_id,created_at desc);

create index if not exists idx_reviews_property on public.reviews(property_id,created_at desc);
create index if not exists idx_reviews_reservation on public.reviews(reservation_id);

create index if not exists idx_room_images_room on public.room_images(room_type_id,sort_order);

create index if not exists idx_webhook_processing on public.payment_webhook_events(processing_status,created_at)
where processing_status in ('received','failed');

create index if not exists idx_idempotency_expiry on public.idempotency_keys(expires_at);
