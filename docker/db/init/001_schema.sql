CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    platform_name VARCHAR(50) NOT NULL,
    asset_symbol VARCHAR(20) NOT NULL,
    action VARCHAR(4) NOT NULL CHECK (action IN ('BUY', 'SELL')),
    quantity_btc NUMERIC(24, 12) NOT NULL CHECK (quantity_btc > 0),
    unit_price_usd NUMERIC(18, 2) NOT NULL CHECK (unit_price_usd > 0),
    fee_usd NUMERIC(18, 2) NOT NULL DEFAULT 0,
    paired_buy_transaction_id BIGINT NULL REFERENCES transactions(id),
    realized_pnl_usd NUMERIC(18, 2) NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    strategy_tag TEXT,
    notes TEXT,
    transaction_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_symbol_executed
ON transactions (asset_symbol, executed_at DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_symbol_transaction_at
ON transactions (asset_symbol, transaction_at DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_open_buys
ON transactions (asset_symbol, action, status)
WHERE action = 'BUY' AND status = 'OPEN';

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
