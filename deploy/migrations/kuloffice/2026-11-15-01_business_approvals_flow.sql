-- The businesses' approval flows (KulOffice internal/approvalflow): what
-- planned each request (the operation, the flow's version and rule), the
-- step it waits for of how many, the fingerprint of what is approved, its
-- channel and amount. Empty on the requests made before the flows.
ALTER TABLE business_approvals ADD COLUMN IF NOT EXISTS operation varchar(48) NOT NULL DEFAULT '';
ALTER TABLE business_approvals ADD COLUMN IF NOT EXISTS policy_version bigint NOT NULL DEFAULT 0;
ALTER TABLE business_approvals ADD COLUMN IF NOT EXISTS rule_id varchar(40) NOT NULL DEFAULT '';
ALTER TABLE business_approvals ADD COLUMN IF NOT EXISTS step bigint NOT NULL DEFAULT 0;
ALTER TABLE business_approvals ADD COLUMN IF NOT EXISTS steps_total bigint NOT NULL DEFAULT 0;
ALTER TABLE business_approvals ADD COLUMN IF NOT EXISTS content_hash varchar(64) NOT NULL DEFAULT '';
ALTER TABLE business_approvals ADD COLUMN IF NOT EXISTS channel varchar(8) NOT NULL DEFAULT '';
ALTER TABLE business_approvals ADD COLUMN IF NOT EXISTS amount_minor bigint NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_business_approvals_operation ON business_approvals (operation);
