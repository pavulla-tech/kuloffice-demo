-- Bills issued in a batch (docs/cobrancas-em-massa in KulOffice): the
-- batch each came from (the code's Bill.BatchID), nil for one made alone.
ALTER TABLE gateway_bills ADD COLUMN IF NOT EXISTS batch_id text;
CREATE INDEX IF NOT EXISTS idx_gateway_bills_batch_id ON gateway_bills (batch_id);
