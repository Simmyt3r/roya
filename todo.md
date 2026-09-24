# iRoya implementation status

## Working foundation

- [x] Preserve legacy PHP prototype branch
- [x] Flask modular application on Vercel
- [x] Replacement Supabase project and v3 migrations
- [x] Supabase/Supavisor production database connectivity
- [x] Supabase Auth sign-in against replacement project
- [x] Guest vs Hotel account-type distinction
- [x] Platform-role privilege guard
- [x] Organization roles: owner, manager, reservations, finance, staff
- [x] Role-aware navigation and post-login routing
- [x] My Stays guest workspace and profile settings
- [x] Hotel organization onboarding and team management
- [x] Property onboarding/editing, amenities and property photos
- [x] Hotel readiness gate before verification
- [x] Room types and editable rate plans
- [x] Range inventory management and 30-day inventory visibility
- [x] Atomic reservation creation, cancellation and hold expiry
- [x] Hotel approval decisions
- [x] Front-desk check-in, check-out and no-show transitions
- [x] Paystack initialization, verification and signed webhook handling
- [x] Paid-cancellation refund request/processing state machine
- [x] PWA manifest, service worker and install workflow
- [x] Demo property seed data
- [x] CI compile + pytest workflow

## Before public launch

- [ ] Deploy the consolidated latest `main` after the current Vercel build-rate limit clears
- [ ] Verify `SUPABASE_SERVICE_ROLE_KEY` is present in production and live-test hotel photo upload
- [ ] Configure/verify Paystack test credentials and webhook delivery
- [ ] Run a complete test payment and refund lifecycle against Paystack test mode
- [x] Enforce refundable-rate cancellation windows before automatic refund requests
- [x] Run authenticated two-user RLS isolation tests on the replacement Supabase project
- [x] Re-run the last-room concurrency race on the replacement Supabase project
- [ ] Enable/review Supabase leaked-password protection
- [ ] Decide whether to remediate remaining PostGIS-owned advisor findings
- [ ] Configure and test SMTP guest/hotel notifications
- [x] Add property/room image deletion, ordering and alt-text editing
- [x] Add invitation flow for hotel staff who do not yet have iRoya accounts
- [x] Add richer search/filtering and location-based discovery
- [x] Replace client-cookie Supabase token storage with private opaque server-side sessions
- [ ] Complete browser/mobile/PWA end-to-end QA
