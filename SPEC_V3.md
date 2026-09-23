# Roya Technical Product Specification v3

Version: 3.0
Date: 2026-09-23
Status: implementation baseline

## 1. Product goal

Roya is the hotel commerce and distribution layer for independent hotels. A hotel organization maintains one reliable source of room inventory and rates; guests receive verified availability and flexible reservation guarantees; future channels distribute the same canonical inventory.

Initial personas are guest, hotel partner/staff and Roya platform administrator.

## 2. Runtime architecture

- Flask / Python 3.12+
- Vercel serverless runtime and Cron
- Supabase PostgreSQL, Auth and Storage
- PostGIS and pg_trgm
- Jinja mobile-first PWA
- Paystack first, behind an internal PaymentProvider interface
- Modular monolith, not microservices

Redis, Celery, Kafka and Kubernetes are intentionally excluded from the pilot.

## 3. Tenancy

The tenancy boundary is organization, not hotel. One organization may own multiple properties. Membership roles are owner, manager, reservations, finance and staff.

Cross-organization access is forbidden. Flask authorization and Supabase RLS provide defence in depth.

## 4. Core data model

Core entities are profiles; organizations and memberships; properties, images and amenities; room types and optional physical rooms; rate plans, rules and daily rates; inventory days; reservations, reservation items and reservation nights; payments, payment transactions, refunds and webhook events; distribution connections and mappings; reviews, notifications, idempotency keys and audit logs.

Money is stored in minor currency units with ISO 4217 codes.

## 5. Inventory invariant

One inventory_days row represents a room type on one date.

Sellable inventory = total_inventory - held_inventory - sold_inventory.

Held plus sold inventory may never exceed total inventory. Missing inventory dates are not assumed to be available.

## 6. Atomic booking

Reservation creation runs inside PostgreSQL. The create_reservation function locks every requested inventory day using row locks, validates capacity and restrictions, calculates daily pricing, creates reservation records and moves inventory before commit.

This database transaction is the serialization point for concurrent Vercel instances.

## 7. State machines

Reservation:
draft, held, pending_confirmation, confirmed, checked_in, checked_out, cancelled, no_show, expired.

Payment:
unpaid, pending, partially_paid, paid, failed, partially_refunded, refunded.

Guarantee:
pay_now, deposit, pay_at_property, hotel_approval.

Reservation state and payment state are separate. A pay-at-property booking may be confirmed and unpaid.

## 8. Holds and expiry

Pay-now and deposit reservations normally hold inventory for 15 minutes. Hotel approval requests may hold longer. Expiry atomically releases held inventory. Vercel Cron invokes the expiry function as maintenance.

## 9. Payments

Paystack is the first provider. Initialization happens server-side. Webhooks validate the Paystack signature, persist an idempotency event fingerprint, validate amount/reference and invoke record_successful_payment to convert held inventory to sold inventory exactly once.

Subaccounts/split settlement are an extension point and are not assumed to be configured.

## 10. Search

Initial search is PostgreSQL-native: indexed property fields, pg_trgm, PostGIS and inventory/rate filtering. Results only include verified active properties with genuinely sellable inventory for the stay dates.

Dedicated search infrastructure is deferred until real scale requires it.

## 11. Authentication and security

Supabase Auth owns credentials. Flask validates sessions and uses secure cookies. Secrets remain server-only. Input is validated with schemas. High-risk operations are audited. API errors use machine-readable codes and request IDs.

RLS protects browser/Supabase API access while Flask also scopes partner queries explicitly.

## 12. Storage

Supabase Storage buckets:
- property-images: public
- room-images: public
- avatars: public
- verification-private: private

Uploads are MIME and size validated.

## 13. Distribution

Internal channel adapters support property, rate and inventory push; reservation pull/acknowledgement; and health checks.

MVP channels are RoyaMarketplaceChannel and DirectBookingChannel. Google Hotels, Booking.com, PMS and other OTA connectors remain future adapters and must not be represented as operational before provider onboarding exists.

## 14. Scheduled work

Protected Vercel Cron endpoints handle expired holds, payment reconciliation, reminders and future channel sync. Jobs must be idempotent and retry-safe.

## 15. MVP flow

Hotel owner registers, creates organization, property, room type, rate and inventory. Roya verifies the property. A guest searches dates, chooses a room/rate, receives an atomic hold or immediate pay-at-property confirmation, completes required payment, and the hotel sees the reservation while inventory stays correct.

## 16. Release gates

Do not merge v3 into main until:
- Python dependencies install and CI tests pass.
- The Supabase migration applies cleanly to a Roya development project.
- RLS tenant isolation is exercised.
- The final-room concurrency test yields one success and one conflict.
- Paystack webhook replay is idempotent.
- A Vercel preview deploys and /health works.
- One complete booking flow succeeds.

## 17. Deferred

Full PMS/POS, payroll/HR, housekeeping, accounting, loyalty wallet, native apps, AI recommendations/dynamic pricing, corporate travel, live OTA connectivity and secondary payment providers.
