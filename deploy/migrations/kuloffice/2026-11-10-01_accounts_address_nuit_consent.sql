-- The accounts' columns that came without a migration (2026-10-31 to
-- 2026-11-04): every new personal account failed on its INSERT. Run by hand
-- on dev on 2026-11-10; kept here so every existing database gets them.
ALTER TABLE accounts
  ADD COLUMN IF NOT EXISTS email_verified_at timestamptz,
  ADD COLUMN IF NOT EXISTS nuit_request_consent_at timestamptz,
  ADD COLUMN IF NOT EXISTS province text,
  ADD COLUMN IF NOT EXISTS district text,
  ADD COLUMN IF NOT EXISTS administrative_post text;
ALTER TABLE orientu_contributions ADD COLUMN IF NOT EXISTS follow boolean;
