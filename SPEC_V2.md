# Roya Technical Product Specification v2 (Laravel, Multi-Tenant)

**Version:** 2.0  
**Date:** 2026-04-27  
**Status:** Draft for implementation

---

## 1) Product Goal

Roya is a multi-tenant hotel booking platform for three personas:

- Guest (customer)
- Hotel Partner (hotelier)
- Admin (platform operations)

This v2 spec converts the MVP concept into an execution-grade blueprint that is safe for production launch and scalable toward enterprise needs.

---

## 2) Technical Stack (Confirmed)

- **Backend Framework:** Laravel 12 (API-first)
- **Language:** PHP 8.3+
- **Database:** PostgreSQL 16 (preferred) or MySQL 8+
- **Auth:** Laravel Sanctum (token-based for SPA/mobile)
- **Queues / Jobs:** Redis + Laravel Queues
- **Cache:** Redis
- **Storage:** Local for dev, S3-compatible in production
- **Payments:** Paystack (primary) with provider abstraction for Flutterwave
- **Notifications:** SMTP email first, optional SMS provider later
- **Observability:** Monolog JSON logs + metrics export + error tracking

---

## 3) System Architecture

### 3.1 High-Level Components

1. API Application (Laravel)
2. Background Workers (queue consumers)
3. Scheduler (reconciliation, reminder jobs)
4. Webhook Ingress endpoint (payments)
5. Admin Dashboard web app (can be Blade + API)

### 3.2 API Design Rules

- All endpoints under `/api/v1`
- JSON request/response only
- UTC timestamps (`ISO-8601`)
- Idempotency required for booking and payment initiation
- Pagination for all list endpoints

### 3.3 Multi-Tenancy Model

Use **shared database, shared schema, tenant-scoped rows**.

- Each hotel-owned resource includes `tenant_id` (for now tenant == hotel owner organization)
- Global tables (e.g., platform admins, supported countries) do not require `tenant_id`
- Enforce tenant scoping in:
  - Eloquent global scopes
  - Policies/Gates
  - Query builders for reporting

**Invariant:** no hotel partner can read or mutate data from another tenant.

---

## 4) Domain Model & Database Design

> Note: use UUID public identifiers for external API (`public_id`) and integer PK internally if desired.

## 4.1 Tables

### users

- id
- public_id (uuid, unique)
- name
- email (unique)
- phone (nullable)
- password_hash
- role enum: `guest | hotel_owner | hotel_staff | admin`
- status enum: `active | suspended | pending_verification`
- email_verified_at (nullable)
- last_login_at (nullable)
- created_at, updated_at

Indexes:
- unique(email)
- index(role, status)

### tenants

- id
- public_id (uuid)
- name
- status enum: `pending | active | suspended`
- created_at, updated_at

Indexes:
- unique(public_id)
- index(status)

### tenant_user_memberships

- id
- tenant_id
- user_id
- membership_role enum: `owner | manager | agent | finance`
- created_at

Constraint:
- unique(tenant_id, user_id)

### hotels

- id
- public_id
- tenant_id
- created_by_user_id
- name
- description
- address
- city
- state
- country
- latitude, longitude
- verification_status enum: `pending | approved | rejected`
- verification_notes (nullable)
- created_at, updated_at

Indexes:
- index(tenant_id)
- index(verification_status)
- full text index(name, city, country)

### hotel_images

- id
- hotel_id
- path
- sort_order
- created_at

### rooms

- id
- public_id
- hotel_id
- name
- description
- base_price_minor (int, store in minor currency unit)
- currency (char(3))
- capacity
- quantity
- is_active (bool)
- created_at, updated_at

Indexes:
- index(hotel_id, is_active)

### room_availability

- id
- room_id
- date
- available_count
- price_override_minor (nullable)
- min_stay_nights (nullable)
- closed_to_arrival (bool default false)
- closed_to_departure (bool default false)
- created_at, updated_at

Constraint:
- unique(room_id, date)

### bookings

- id
- public_id
- tenant_id
- user_id
- hotel_id
- room_id
- check_in (date)
- check_out (date)
- nights
- guests
- unit_price_minor
- total_price_minor
- currency
- status enum: `pending | confirmed | cancelled | completed | no_show`
- payment_status enum: `unpaid | pending | paid | failed | refunded | partially_refunded`
- cancellation_reason (nullable)
- cancelled_at (nullable)
- confirmed_at (nullable)
- completed_at (nullable)
- created_at, updated_at

Indexes:
- unique(public_id)
- index(tenant_id, status)
- index(user_id, created_at)
- index(hotel_id, check_in, check_out)

### booking_nights

- id
- booking_id
- room_id
- date
- quantity_reserved

Constraint:
- unique(booking_id, date)

Purpose:
- deterministic inventory accounting per date to avoid overbooking.

### payments

- id
- public_id
- booking_id
- provider enum: `paystack | flutterwave`
- amount_minor
- currency
- method (nullable)
- status enum: `initiated | pending | successful | failed | refunded | partially_refunded`
- provider_transaction_ref (unique)
- provider_payload_json
- paid_at (nullable)
- created_at, updated_at

Indexes:
- unique(provider_transaction_ref)
- index(booking_id, status)

### payment_webhook_events

- id
- provider
- event_id (unique)
- signature_valid (bool)
- payload_json
- processed_at (nullable)
- processing_status enum: `received | processed | ignored | failed`
- created_at

### reviews

- id
- user_id
- hotel_id
- booking_id
- rating (tinyint 1-5)
- comment
- is_visible (bool)
- created_at, updated_at

Constraint:
- unique(user_id, booking_id)

### audit_logs

- id
- actor_user_id (nullable for system jobs)
- tenant_id (nullable)
- action
- entity_type
- entity_id
- before_json
- after_json
- ip_address
- user_agent
- created_at

Indexes:
- index(tenant_id, created_at)
- index(entity_type, entity_id)

---

## 5) State Machines (Non-Negotiable)

## 5.1 Booking Status

Allowed transitions:

- `pending -> confirmed`
- `pending -> cancelled`
- `confirmed -> completed`
- `confirmed -> cancelled`
- `confirmed -> no_show`

Forbidden:
- No direct `pending -> completed`
- No transitions out of `cancelled`

## 5.2 Payment Status

Allowed transitions:

- `unpaid -> pending`
- `pending -> paid`
- `pending -> failed`
- `paid -> refunded`
- `paid -> partially_refunded`

Invariant:
- Booking cannot be `confirmed` unless payment is `paid` (unless explicit pay-later policy enabled per hotel).

---

## 6) Roles and Permissions

## 6.1 Guest

- Register/login/logout
- Search hotels and rooms
- Create/cancel own bookings
- Pay for own bookings
- View own payment history
- Create review only if booking `completed`

## 6.2 Hotel Owner/Staff

- Manage own hotel profile, rooms, inventory, pricing
- View and manage own tenant bookings
- Update operational statuses (`confirmed`, `completed`, `no_show`, cancellation with reason)
- View earnings and payout reports (if enabled)

## 6.3 Admin

- Approve/reject hotels and tenant onboarding
- Suspend/reactivate users/tenants
- Review disputes and force refunds
- Access platform-wide analytics and finance dashboards

All write operations must create `audit_logs` entries.

---

## 7) Core Booking & Availability Logic

## 7.1 Availability Query

For each date in `[check_in, check_out)`:

- Effective stock = `room_availability.available_count` if present else `rooms.quantity`
- Reserved stock = sum(`booking_nights.quantity_reserved`) for bookings in states `pending` or `confirmed`
- Sellable stock = `effective - reserved`

A booking is allowed only if sellable stock >= requested quantity for **all** nights.

## 7.2 Concurrency Control

During booking creation:

1. Begin DB transaction
2. Lock targeted `room_availability` (or deterministic room stock row) for all requested nights using `FOR UPDATE`
3. Recompute sellable stock inside transaction
4. Insert `bookings` (`status=pending`, `payment_status=pending`)
5. Insert `booking_nights`
6. Commit

If any night fails stock check -> rollback and return conflict (`409`).

## 7.3 Booking Timeout

`pending` bookings auto-expire after configurable TTL (e.g., 15 minutes) if unpaid.
Scheduled job cancels expired bookings and releases inventory.

---

## 8) Payments (Paystack / Flutterwave)

## 8.1 Initiation

- Client calls `POST /api/v1/payments/initiate`
- Server creates payment record (`initiated`) and provider transaction reference
- Server returns redirect/auth URL

## 8.2 Webhook Processing

1. Validate provider signature
2. Check idempotency using `event_id`/transaction reference
3. Persist raw event in `payment_webhook_events`
4. Update `payments.status`
5. Update booking payment + booking status (if successful)
6. Queue notifications

Webhook must be retry-safe and idempotent.

## 8.3 Reconciliation Job

Nightly job compares provider transaction statuses with local records.
- Auto-heal inconsistent states
- Alert finance/admin for unresolved mismatches

---

## 9) API Contract

## 9.1 Response Envelope

Success:

```json
{
  "success": true,
  "data": {},
  "meta": {
    "request_id": "..."
  }
}
```

Error:

```json
{
  "success": false,
  "error": {
    "code": "BOOKING_CONFLICT",
    "message": "Selected room is no longer available for one or more dates",
    "details": {}
  },
  "meta": {
    "request_id": "..."
  }
}
```

## 9.2 Pagination Standard

Query params:
- `page` (default 1)
- `per_page` (default 20, max 100)

Response meta includes `total`, `page`, `per_page`, `last_page`.

## 9.3 Key Endpoints

### Auth
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

### Hotels
- `GET /api/v1/hotels`
- `GET /api/v1/hotels/{hotel_public_id}`
- `POST /api/v1/hotels` (hotel owner)
- `PUT /api/v1/hotels/{hotel_public_id}`
- `POST /api/v1/hotels/{hotel_public_id}/images`

### Rooms & Availability
- `POST /api/v1/rooms`
- `PUT /api/v1/rooms/{room_public_id}`
- `GET /api/v1/hotels/{hotel_public_id}/rooms`
- `PUT /api/v1/rooms/{room_public_id}/availability`

### Bookings
- `POST /api/v1/bookings`
- `GET /api/v1/bookings` (scoped by role)
- `GET /api/v1/bookings/{booking_public_id}`
- `PUT /api/v1/bookings/{booking_public_id}/cancel`

### Payments
- `POST /api/v1/payments/initiate`
- `POST /api/v1/payments/webhooks/paystack`
- `POST /api/v1/payments/webhooks/flutterwave`

### Reviews
- `POST /api/v1/reviews`
- `GET /api/v1/hotels/{hotel_public_id}/reviews`

### Admin
- `GET /api/v1/admin/metrics`
- `PUT /api/v1/admin/hotels/{hotel_public_id}/approval`
- `PUT /api/v1/admin/users/{user_public_id}/status`
- `GET /api/v1/admin/payments`

---

## 10) Security & Compliance Requirements

- Password hashing: Argon2id/Bcrypt via Laravel defaults
- Strict input validation via Form Requests
- Rate limiting for auth, search, and payment initiation endpoints
- CSRF protection for web sessions; token auth for API
- Signed webhook validation required
- PII access logs and audit logs retention policy
- Secrets in env vars only (no plaintext in source control)

---

## 11) Observability, Logging, and Alerts

- Every request gets `request_id`
- Structured JSON logs for:
  - booking create/cancel errors
  - payment initiation failures
  - webhook processing failures
- Metrics:
  - booking success rate
  - payment success/failure rate
  - overbooking prevention conflicts (`409`)
  - webhook lag and failure counts
- Alerts:
  - repeated webhook failures
  - reconciliation mismatches
  - error rate spikes

---

## 12) Non-Functional Targets (MVP Production)

- API availability: **99.9% monthly**
- P95 read latency: **< 300ms**
- P95 booking create latency: **< 800ms**
- Webhook processing: **< 60s** from receive to persisted update
- RPO: **15 min**, RTO: **4 hrs**

---

## 13) Migration Plan from Current Prototype

## Phase 1: Foundation (2 weeks)

- Create Laravel API project scaffold
- Implement auth, role middleware, tenant scaffolding
- Create migrations for v2 tables

## Phase 2: Core Domain (3 weeks)

- Hotels, rooms, availability endpoints
- Booking engine with locking + idempotency
- Unit/integration tests for inventory logic

## Phase 3: Payments + Notifications (2 weeks)

- Payment provider abstraction
- Paystack integration + secure webhooks
- Confirmation/cancellation notifications

## Phase 4: Admin + Reporting (2 weeks)

- Admin approval flows
- Core metrics dashboard APIs
- Audit log browse endpoints

## Phase 5: Hardening & Launch (2 weeks)

- Load test booking paths
- Security review and secret audit
- Staging UAT with pilot hotels

---

## 14) Test Strategy

- **Unit tests:** pricing, availability computations, policy checks
- **Feature/API tests:** auth, booking flow, payment callbacks
- **Concurrency tests:** simultaneous booking attempts on same room/date
- **Contract tests:** provider webhook payload handling
- **Smoke tests:** post-deploy API health and critical paths

Release gate: no launch if booking concurrency tests fail.

---

## 15) Out of Scope for MVP (Explicit)

- Multi-currency settlement engine
- Loyalty points/wallet
- AI recommendation systems
- Dynamic yield management with external demand signals
- Full native mobile app

---

## 16) Open Questions

1. Do we enable pay-later for trusted hotels or force pay-now only?
2. What is the default cancellation policy and refund window?
3. Are payouts to hotel partners required in MVP or post-MVP?
4. Which provider is primary at launch: Paystack only or dual-provider?
5. Do we support hotel staff sub-accounts in MVP or phase 2?

