-- The dates a plan change's document carries (document_requirements, KO-12),
-- added to the model without a migration (alpha42): every plan change with a
-- document failed on its INSERT. Run by hand on dev on 2026-11-11; kept here
-- so every existing database gets them.
ALTER TABLE business_plan_change_documents
  ADD COLUMN IF NOT EXISTS issued_on timestamptz,
  ADD COLUMN IF NOT EXISTS expires_on timestamptz;
