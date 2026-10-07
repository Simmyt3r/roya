-- Cover the new housekeeping actor foreign key for delete/update checks.
create index if not exists idx_physical_rooms_housekeeping_updated_by
  on public.physical_rooms(housekeeping_updated_by)
  where housekeeping_updated_by is not null;
