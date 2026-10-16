# iRoya v1.0 Release Freeze

## Baseline

The v1.0 release-candidate baseline is commit:

`3c8ea07f4429442fbf02be180f76c2765938da08`

An untouched reference branch is retained as:

`release/v1.0-rc-baseline`

All release work must happen on `release/v1.0-hardening` or a descendant and must be limited to correctness, security, reliability, deployment, observability, accessibility, performance, documentation, or test changes.

## Freeze rule

No new product feature, workflow, page, integration, data model capability, monetization feature, or scope expansion is allowed before v1.0.

A change may enter the release only when it either:

1. fixes a reproducible defect;
2. closes a security or privacy weakness;
3. improves correctness or transaction safety;
4. improves deployment or operational reliability;
5. adds or strengthens tests without changing product scope;
6. resolves accessibility or mobile usability defects already present in the baseline; or
7. documents an existing release requirement.

## v1.0 release gates

- [x] RC baseline preserved.
- [x] Feature freeze documented.
- [x] Production Flask signing secret configured.
- [x] Production environment mode configured.
- [x] Working production APP_URL configured.
- [x] Vercel CRON_SECRET configured.
- [x] Browser security headers hardened.
- [x] Database-backed throttling added for login, registration and payment initiation.
- [x] Security-sensitive GitHub Actions pinned to immutable SHAs.
- [x] Dependency vulnerability audit added to CI and currently passing.
- [x] RC coverage baseline measured and protected against regression.
- [x] Hardened branch test/compile/dependency CI passes.
- [x] Private rate-limit migration applied and browser-role grants verified absent.
- [x] PostGIS RPC privilege-drift remediation migration applied and effective ACL rechecked.
- [ ] Resolve or formally accept the Supabase-managed PostGIS `st_estimatedextent` EXECUTE advisory; the extension-owned ACL remains executable by `anon` and `authenticated` despite the application migration.
- [ ] Enable Supabase leaked-password protection where the project plan/control surface permits it.
- [ ] Production deployment of the hardening PR passes /health and smoke checks.
- [ ] Paystack test keys configured.
- [ ] Booking -> Paystack -> webhook -> reconciliation -> refund lifecycle certified.
- [ ] iroya.ng and wildcard hotel-domain DNS configured and verified.
- [ ] APP_URL cut over from iroya.vercel.app to https://iroya.ng after DNS verification.
- [ ] Mobile/browser/PWA acceptance run passes on real devices.
- [ ] Final QA/QC audit returns no P0/P1 launch blockers.

## Managed PostGIS note

The PostGIS functions `public.st_estimatedextent(...)` are owned by Supabase's `supabase_admin` extension role. The v1.0 remediation migration executes successfully as the project `postgres` role, but that role cannot modify the extension-owned ACL. Production recheck therefore still reports anonymous and authenticated EXECUTE privileges. Do not grant elevated Supabase-managed roles merely to silence this advisory; resolve it through a supported Supabase control path or document a vendor-supported acceptance before v1.0.

## Version rule

Do not create or advertise `v1.0.0` until every unchecked release gate above has passed.
