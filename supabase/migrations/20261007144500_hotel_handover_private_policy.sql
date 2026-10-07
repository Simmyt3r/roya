-- The handover table migration reached production before the explicit deny
-- policy was added to its source file. Add the policy as a forward migration.

drop policy if exists hotel_handover_notes_no_client_access
  on private.hotel_handover_notes;

create policy hotel_handover_notes_no_client_access
on private.hotel_handover_notes
for all
to anon,authenticated
using (false)
with check (false);

revoke all on table private.hotel_handover_notes from public,anon,authenticated;
