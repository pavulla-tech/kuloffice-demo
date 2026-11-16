-- A rule's ceiling counts this business's account as a whole (account) or
-- each member's own requests from it (member); empty with no ceiling
-- (KulOffice internal/approvalflow, AF-12).
ALTER TABLE approval_rules ADD COLUMN IF NOT EXISTS cumulative_scope varchar(8) NOT NULL DEFAULT '';
