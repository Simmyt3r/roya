# Roya v3 project structure

Roya v3 is a Flask modular monolith.

- app.py: Vercel/WSGI entry point
- roya/: domain modules
- templates/: server-rendered guest, partner and admin screens
- static/: PWA and lightweight UI assets
- supabase/: versioned schema, RLS and seed material
- tests/: unit and integration contracts
- scripts/: acceptance utilities such as final-room concurrency checking

The old procedural PHP layout is preserved on legacy-php-prototype and is not the v3 runtime.
