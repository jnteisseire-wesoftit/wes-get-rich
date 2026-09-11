-- Add support for DEPOSIT and WITHDRAWAL transactions
-- This allows tracking fiat deposits, withdrawals, and associated fees

-- Drop the view that depends on the action column
DROP VIEW IF EXISTS transaction_overview;

-- Expand the action column to allow longer values
ALTER TABLE transactions
ALTER COLUMN action TYPE VARCHAR(12);

-- Update the action constraint to include DEPOSIT and WITHDRAWAL
ALTER TABLE transactions
DROP CONSTRAINT transactions_action_check;

ALTER TABLE transactions
ADD CONSTRAINT transactions_action_check 
CHECK (action IN ('BUY', 'SELL', 'DEPOSIT', 'WITHDRAWAL'));

-- For deposits/withdrawals, quantity_btc can be 0
-- Make quantity_btc nullable for deposits/withdrawals where it's not relevant
ALTER TABLE transactions
ALTER COLUMN quantity_btc DROP NOT NULL;

-- Make unit_price_usd nullable for deposits/withdrawals
ALTER TABLE transactions
ALTER COLUMN unit_price_usd DROP NOT NULL;

-- Recreate the view
CREATE OR REPLACE VIEW transaction_overview AS
SELECT
    t.id,
    t.platform_name,
    t.asset_symbol,
    t.action,
    t.quantity_btc,
    t.unit_price_usd,
    t.fee_usd,
    t.realized_pnl_usd,
    t.status,
    t.paired_buy_transaction_id,
    t.strategy_tag,
    t.transaction_at,
    t.executed_at
FROM transactions t
ORDER BY t.transaction_at DESC;
