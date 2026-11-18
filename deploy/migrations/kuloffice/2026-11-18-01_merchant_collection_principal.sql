-- A business's principal collection account (KulOffice internal/merchantcollections
-- principal.go): opened when the business becomes active, with its fixed QR code.
ALTER TABLE merchant_collection_accounts ADD COLUMN IF NOT EXISTS principal boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_merchant_collection_accounts_principal ON merchant_collection_accounts (principal);
