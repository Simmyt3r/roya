# Roya v3

Roya is a hotel commerce, inventory and distribution platform for independent hotels. The v3 rebuild uses Flask on Vercel with Supabase PostgreSQL/Auth/Storage and Paystack.

SPEC_V2.md is retained for history. SPEC_V3.md is the current technical source of truth.

## Architecture

- Python 3.12+ / Flask modular monolith
- Jinja mobile-first server rendering
- Supabase PostgreSQL + PostGIS + pg_trgm
- Supabase Auth and Storage
- Atomic PostgreSQL reservation functions for inventory integrity
- Vercel serverless deployment and Cron
- Paystack provider adapter and signed webhook processing

## Local setup

1. python -m venv .venv
2. Activate the virtual environment.
3. pip install -r requirements-dev.txt
4. Copy .env.example to .env.
5. Run: flask --app app run --debug

The public home page and /health can load without a database. Search, authentication, partner and booking workflows require Supabase configuration.

## Environment

Configure FLASK_SECRET_KEY, APP_URL, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SERVICE_ROLE_KEY, DATABASE_URL, PAYSTACK_SECRET_KEY and CRON_SECRET.

SUPABASE_ANON_KEY remains supported as a legacy fallback. DATABASE_URL should use the Supabase/Supavisor transaction pooler for serverless application traffic. Never expose the Supabase service-role key, database password, Flask secret, cron secret or Paystack secret to browser code.

## Supabase

The current Roya project is ref `nagadxvccyiilowcuruk` in `ap-southeast-1`.

Apply migrations in order from supabase/migrations. The foundation migration creates multi-property tenancy, room types/rates, per-day inventory, reservations, payment records, RLS, storage buckets, PostGIS and atomic inventory functions. Follow-up migrations harden RLS/RPC exposure, move the tenancy helper to a private schema, add operational indexes, schedule hold expiry, and add atomic hotel-approval decisions.

supabase/seed.sql is development-only and must not run automatically in production.

## Reservation integrity

create_reservation(...) lives in PostgreSQL. It locks every requested inventory_days row, recomputes sellable inventory and moves stock in the same transaction. Flask never performs a separate check-then-insert booking flow.

Reservation and payment states are independent. A pay-at-property reservation may be confirmed while unpaid.

The booking lock design has been live-tested against a final-room race: one transaction succeeded and the competing transaction returned BOOKING_CONFLICT; inventory never went negative.

## Tests

Run pytest for unit tests.

The repository also contains scripts/concurrency_check.py for a full reservation-function race test once a disposable Auth fixture and TEST_DATABASE_URL are available. Do not weaken or bypass Supabase Auth merely to manufacture that fixture.

## Vercel

Production project: `iroya`.

Configure the environment values above. vercel.json routes all traffic into the Flask function and includes templates/static assets in the Python bundle. Reservation hold expiry runs in Supabase Cron; Vercel handles the lower-frequency internal cron routes.

## Paystack

Configure the webhook URL as /api/webhooks/paystack. Roya validates x-paystack-signature against the raw request body. Browser redirects never mark a transaction successful.

## Legacy

The procedural PHP/MySQL prototype is preserved on the legacy-php-prototype branch. See MIGRATION.md for the domain mapping.
