# Database functions

Critical inventory mutations live in PostgreSQL:

- create_reservation: locks every requested inventory day before reserving.
- cancel_reservation: releases held or sold inventory atomically.
- expire_reservation_holds: expires stale holds with row locks.
- record_successful_payment: idempotently converts a paid hold to sold inventory.

This prevents concurrent Vercel function instances from overselling the final room.
