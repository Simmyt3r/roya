# Roya legacy to v3 migration map

The procedural PHP/MySQL prototype is a design reference, not the target runtime.

| Legacy | Roya v3 |
| --- | --- |
| hotel account/password | Supabase Auth + profile + organization membership |
| one hotel per account | organization with many properties |
| hotel_profiles photos JSON | property_images + Supabase Storage |
| pricing JSON | rate_plans + daily_rates |
| availability JSON | inventory_days |
| no room-type ledger | room_types + optional physical_rooms |
| users password table | Supabase Auth |
| bookings | reservations + items + nights |
| Stripe-style payment field | payments + payment_transactions + Paystack |
| admins password table | profiles.platform_role = admin |

There is no evidence in this repository of an attached live MySQL database. Before any real import, export the source database, count every entity, preserve foreign-key mapping and reconcile reservation/payment totals.

Do not import plaintext or legacy password hashes into Supabase Auth as user passwords.
