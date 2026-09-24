# iRoya

iRoya is hotel commerce and distribution infrastructure for independent hotels. The current product is built around a canonical hotel inventory/rate source that can serve direct booking today and additional distribution channels later.

`SPEC_V2.md` is retained for history. `SPEC_V3.md` is the current technical source of truth.

## Architecture

- Python 3.12+ / Flask modular monolith
- Jinja mobile-first UI and installable PWA
- Supabase PostgreSQL + Auth + Storage
- PostGIS and pg_trgm for location/search evolution
- Atomic PostgreSQL reservation functions for inventory integrity
- Vercel serverless deployment and Cron
- Paystack provider adapter, signed webhooks, reconciliation and refund workflow

## Roles

iRoya deliberately separates three different concepts:

- **Account type:** `guest` / `hotel` controls the product workspace and navigation.
- **Platform role:** `user` / `admin` / `support` / `finance` controls iRoya platform permissions.
- **Hotel organization role:** `owner` / `manager` / `reservations` / `finance` / `staff` controls access inside a hotel organization.

A hotel team member can still use the same account to make personal bookings. Organization membership does not expose another user's personal reservation history.

## Hotel workflow

A hotel account can create an organization, add properties, maintain guest-facing details and amenities, upload property photos, create and edit room types and rate plans, load inventory ranges, inspect a 30-day inventory view, add hotel team members, approve hotel-approval reservations, operate front-desk check-in/check-out/no-show states, and process eligible refund requests.

A property cannot be verified for public sale until it has at least one active room type, one active rate plan and future sellable inventory. Changing a verified property's identity or physical location returns it to verification.

## Guest workflow

Guests can search verified active properties, inspect live sellable rooms for selected dates, reserve with atomic inventory protection, use pay-now/deposit/pay-at-property/hotel-approval guarantees, manage reservations in **My Stays**, continue required payments, cancel unpaid eligible reservations, and request refund review for paid cancellations.

Browser redirects never mark a Paystack transaction successful. iRoya verifies Paystack responses and signed webhooks before changing payment state.

## Local setup

1. `python -m venv .venv`
2. Activate the virtual environment.
3. `pip install -r requirements-dev.txt`
4. Copy `.env.example` to `.env`.
5. Run `flask --app app run --debug`.

The public landing page can render without a database. Database-backed health, search, account, hotel, reservation and payment workflows require their configured services.

## Environment

Configure:

- `FLASK_SECRET_KEY`
- `APP_URL`
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY` for privileged Storage/server operations
- `DATABASE_URL` using the Supabase/Supavisor transaction pooler for serverless traffic
- `PAYSTACK_SECRET_KEY`
- `CRON_SECRET`
- SMTP values when email notifications are enabled

`SUPABASE_ANON_KEY` remains supported as a legacy fallback. Never expose the Supabase service-role key, database password, Flask secret, cron secret or Paystack secret to browser code.

## Supabase

Current production project ref: `nagadxvccyiilowcuruk` in `ap-southeast-1`.

Apply migrations in order from `supabase/migrations`. The current production database includes the v3 foundation/security/index/cron/partner-decision migrations plus the guest-vs-hotel account type migration.

`supabase/seed.sql` is development/demo data and must not run automatically as production content.

## Reservation integrity

`create_reservation(...)` runs inside PostgreSQL. It locks every requested `inventory_days` row, recomputes sellable inventory, writes reservation nights and moves held/sold stock in one transaction. Flask does not use a separate check-then-insert booking flow.

Reservation and payment states are independent. A pay-at-property reservation may be confirmed while unpaid.

The locking design was race-tested on the earlier project. The replacement Supabase project still needs its own fresh concurrency acceptance run before launch.

## Payments and refunds

Paystack payment initialization is idempotency-key protected. Signed webhooks and server-side verification drive successful payment state.

Paid cancellation does not immediately cancel inventory. It creates refund review records. Authorized hotel roles initiate Paystack refunds; iRoya waits for refund processing/webhooks and only releases a still-active reservation after the captured amount has been fully refunded. Cancellation-policy enforcement still needs its final policy engine before public launch.

## Tests

CI runs Python 3.12 compilation and `pytest` on every push to `main`.

A separate `scripts/concurrency_check.py` is available for the live last-room race test once disposable authenticated test users and `TEST_DATABASE_URL` are prepared.

## Vercel

Production project: `iroya`.

`vercel.json` routes application traffic to Flask and bundles templates/static assets. High-frequency reservation-hold expiry is handled by Supabase Cron; lower-frequency operational jobs remain available through protected internal cron routes.

## Legacy

The procedural PHP/MySQL prototype remains on `legacy-php-prototype`. See `MIGRATION.md` for domain mapping.
