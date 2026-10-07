-- Cover the reservation_notes organization foreign key for scoped operations queries.
create index if not exists idx_reservation_notes_organization
  on private.reservation_notes(organization_id);
