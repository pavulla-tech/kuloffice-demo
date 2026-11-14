-- Business plans are Kulpay's internal classification (owner, 2026-11-14;
-- KulOffice claude/plan-internal): every new business starts on Lite and an
-- operator assigns the plan, at the onboarding approval or on a review the
-- business asks for («rever o meu plano»).

-- What the business tells at onboarding, and when its plan was assigned.
ALTER TABLE accounts
  ADD COLUMN IF NOT EXISTS business_expected_monthly_volume varchar(16),
  ADD COLUMN IF NOT EXISTS business_sales_channels varchar(64),
  ADD COLUMN IF NOT EXISTS business_activity varchar(120),
  ADD COLUMN IF NOT EXISTS business_plan_assigned_at timestamptz;

-- A plan request may name no plan (a review); it carries the expected
-- volume, a note, and the plan the operator decided.
ALTER TABLE business_plan_change_requests
  ADD COLUMN IF NOT EXISTS expected_monthly_volume varchar(16),
  ADD COLUMN IF NOT EXISTS note varchar(1000),
  ADD COLUMN IF NOT EXISTS decided_plan varchar(24);

-- The plan the operator assigns with a business's onboarding approval.
ALTER TABLE operator_decisions
  ADD COLUMN IF NOT EXISTS plan varchar(24) NOT NULL DEFAULT '';

-- Requests decided before: the plan they assigned or kept.
UPDATE business_plan_change_requests SET decided_plan = to_plan
  WHERE status = 'approved' AND (decided_plan IS NULL OR decided_plan = '');
UPDATE business_plan_change_requests SET decided_plan = from_plan
  WHERE status = 'rejected' AND (decided_plan IS NULL OR decided_plan = '');
