-- Lightweight room readiness / housekeeping workflow.
-- Physical room tracking stays optional. Hotels that do not configure room numbers
-- keep the existing room-type inventory and check-in flow unchanged.

alter table public.physical_rooms
  add column if not exists housekeeping_status text not null default 'ready',
  add column if not exists housekeeping_updated_at timestamptz,
  add column if not exists housekeeping_updated_by uuid references auth.users(id) on delete set null,
  add column if not exists current_reservation_id uuid references public.reservations(id) on delete set null,
  add column if not exists assigned_at timestamptz;

alter table public.physical_rooms
  drop constraint if exists physical_rooms_housekeeping_status_check;

alter table public.physical_rooms
  add constraint physical_rooms_housekeeping_status_check
  check(housekeeping_status in ('dirty','cleaning','ready'));

create index if not exists idx_physical_rooms_readiness
  on public.physical_rooms(room_type_id,status,housekeeping_status);

create index if not exists idx_physical_rooms_current_reservation
  on public.physical_rooms(current_reservation_id)
  where current_reservation_id is not null;

comment on column public.physical_rooms.housekeeping_status is
  'Operational readiness for active physical rooms: dirty, cleaning, or ready. Out-of-service is represented by physical_rooms.status.';

comment on column public.physical_rooms.current_reservation_id is
  'Current checked-in reservation assigned to this physical room. Null when unoccupied/unassigned.';
