-- Portal v2 E5 (KulOffice claude/portal-v2): the product catalogue's four
-- eyes. A revision is proposed by one operator and published by another
-- (edited_by, proposed_by, proposed_at, reason, decided_by, decision_note);
-- a retirement is proposed and decided by another (retire_proposed_by,
-- retire_proposed_at, retire_reason). Revisions published before keep
-- empty values. New tables (customer_notes, product_allocations) come from
-- their create_ migrations.
ALTER TABLE product_definition_revisions
  ADD COLUMN IF NOT EXISTS edited_by text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS proposed_by text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS proposed_at timestamptz,
  ADD COLUMN IF NOT EXISTS reason text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS decided_by text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS decision_note text NOT NULL DEFAULT '';
ALTER TABLE product_definitions
  ADD COLUMN IF NOT EXISTS retire_proposed_by text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS retire_proposed_at timestamptz,
  ADD COLUMN IF NOT EXISTS retire_reason text NOT NULL DEFAULT '';
