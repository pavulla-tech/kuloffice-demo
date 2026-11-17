-- A request KulPay's back office cancelled while it waited (KulOffice
-- internal/businessapproval, AF-15): the reason the business is told, and
-- the operator's note, which it never is.
ALTER TABLE business_approvals ADD COLUMN IF NOT EXISTS cancel_reason varchar(32) NOT NULL DEFAULT '';
ALTER TABLE business_approvals ADD COLUMN IF NOT EXISTS cancel_note varchar(1000) NOT NULL DEFAULT '';
