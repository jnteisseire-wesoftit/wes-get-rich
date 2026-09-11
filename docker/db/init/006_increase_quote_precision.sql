-- Preserve Kraken fees and prices to four decimal places in quote currency.
ALTER TABLE transactions
    ALTER COLUMN unit_price_usd TYPE NUMERIC(18, 4),
    ALTER COLUMN fee_usd TYPE NUMERIC(18, 4),
    ALTER COLUMN realized_pnl_usd TYPE NUMERIC(18, 4);