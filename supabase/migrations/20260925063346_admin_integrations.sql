-- Credential values live in Supabase Vault; this table holds only configuration
-- and an opaque Vault secret id. The private schema is outside the Data API.
create table if not exists private.integration_settings (
  provider text primary key check (provider in ('smtp', 'paystack')),
  configuration jsonb not null default '{}'::jsonb
    check (jsonb_typeof(configuration) = 'object'),
  secret_id uuid,
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now()
);

alter table private.integration_settings enable row level security;
revoke all on table private.integration_settings from public, anon, authenticated;
