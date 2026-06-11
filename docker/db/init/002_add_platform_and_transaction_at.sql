ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS platform_name VARCHAR(50);

ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS transaction_at TIMESTAMPTZ;

UPDATE transactions
SET platform_name = COALESCE(platform_name, 'manual')
WHERE platform_name IS NULL;

UPDATE transactions
SET transaction_at = COALESCE(transaction_at, executed_at, NOW())
WHERE transaction_at IS NULL;

ALTER TABLE transactions
ALTER COLUMN platform_name SET NOT NULL;

ALTER TABLE transactions
ALTER COLUMN transaction_at SET NOT NULL;
