-- Portal v2 E6 (KulOffice claude/portal-v2): a concession's estimated cost
-- a month (its simulation's lost revenue over 30 days). Above the
-- concession_approvals policy's threshold (5 000 MT by default) Finance
-- decides it (concession:approve_finance). Concessions proposed before
-- keep 0.
ALTER TABLE pricing_concessions ADD COLUMN IF NOT EXISTS monthly_cost_minor bigint NOT NULL DEFAULT 0;
