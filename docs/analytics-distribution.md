# Analytics and Distribution Semantics

This note documents the operational meaning of the hotel analytics and distribution surfaces introduced after the Finance Center. It is intentionally explicit so future channel integrations do not reinterpret the same numbers or silently bypass iRoya's canonical inventory model.

## Hotel performance analytics

Access is limited to active organization members with the `owner`, `manager`, or `finance` role.

The report accepts an organization/property scope and a date range of at most 367 days.

### Metric basis

Inventory and room-revenue metrics use **stay dates** in the selected period.

- **Capacity room-nights**: sum of `inventory_days.total_inventory`.
- **Sold room-nights**: sum of `inventory_days.sold_inventory`.
- **Held room-nights**: sum of `inventory_days.held_inventory`.
- **Remaining sellable room-nights**: total minus sold minus held for dates that are not under stop-sell.
- **Occupancy**: sold room-nights divided by capacity room-nights.
- **Booked room-nights**: sum of `reservation_nights.quantity` for confirmed, checked-in, and checked-out reservations.
- **Room revenue**: sum of `reservation_nights.unit_price_minor * quantity` for those active/completed reservation states.
- **ADR**: room revenue divided by booked room-nights.
- **RevPAR**: room revenue divided by capacity room-nights.

Booking-behaviour metrics use reservations **created during** the selected period:

- active bookings
- cancellations and no-shows
- cancellation rate
- average booking lead time
- average length of stay
- guarantee mix
- reservation-status mix

Guest rating uses visible reviews created in the selected period.

### Booking source attribution

Every reservation stores a `source_channel`. Main-domain iRoya bookings are attributed to `roya_marketplace`; reservations created from a matching verified hotel mini-domain are attributed to `direct_booking`; hotel-created phone, WhatsApp and walk-in reservations are attributed to `front_desk`. A hotel mini-domain cannot create a reservation for another property.

Idempotent reservation replays preserve the original source rather than overwriting it. Analytics groups reservation count, booking value and cancellations by source channel.

All money values remain stored and calculated in minor currency units until display/export formatting.

## Distribution manager

Distribution management is limited to active organization `owner` and `manager` roles.

The canonical source of hotel content, room types, rates, restrictions, and inventory remains iRoya. The distribution layer must not create a second inventory source.

### Operational MVP channels

Only these adapters are operational:

- `direct_booking` -> `DirectBookingChannel`
- `roya_marketplace` -> `RoyaMarketplaceChannel`

These are built-in channels and do not require external provider credentials.

Opening the Distribution Manager is read-only. A channel connection is created or updated only after an explicit sync request. The database enforces one property/channel connection with a unique partial index.

After initialization, an active built-in connection is eligible for scheduled synchronization once per day. Owners/managers may pause a connection by moving it to `disconnected`; disconnected connections are ignored by scheduled sync. Manual sync resumes a disconnected built-in channel.

A manual or scheduled sync currently performs:

1. adapter health check
2. property push
3. rate push
4. inventory push
5. reservation pull
6. persistent sync logging
7. connection status/last-sync update
8. audit logging

Sync logs record whether the trigger was `manual` or `scheduled`. The connection settings retain health, last trigger, last attempt timestamp and last sync status. A transaction-level advisory lock plus database uniqueness prevents duplicate initialization of the same property/channel pair.

### Future adapters

Booking.com, Google Hotels, external PMS/channel managers, and other OTA connectors remain non-operational until actual provider onboarding, contracts/API access, credentials, mapping requirements, and synchronization behaviour are implemented.

The UI may identify them as future adapters but must not imply that they are connected or usable.

Future provider secrets must remain server-side and should use the established secret/Vault pattern. They must never be stored in browser-visible channel settings.

## Database security

The existing `channel_connections`, `channel_room_mappings`, and `channel_sync_logs` tables remain backend-only. RLS is enabled with deny-all browser/Data API policies. Flask services explicitly scope every hotel operation to organization membership.

No distribution connection, room mapping, or sync-log record is seeded merely by deploying this feature.
