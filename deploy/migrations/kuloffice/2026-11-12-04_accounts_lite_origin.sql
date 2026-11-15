-- KYC da conta Lite (KulOffice claude/lite-kyc, docs/kyc-conta-lite):
-- an account opened as KulPay Lite (USSD) keeps the Lite limits until its
-- KYC is approved, also while it is being reviewed and after a rejection.
-- lite_origin marks it; the account's own kyc_status moves on with the KYC.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS lite_origin boolean NOT NULL DEFAULT false;

-- Lite today, and Lite accounts whose KYC was submitted but not approved
-- (their ledger identity is still the phone-only Lite one).
UPDATE accounts SET lite_origin = true
WHERE type = 'personal' AND lite_origin = false AND (
  kyc_status = 'lite'
  OR (kyc_status <> 'verified' AND id IN (SELECT account_id FROM customer_ledger_identities WHERE lite = true))
);
