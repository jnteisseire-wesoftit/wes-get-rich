-- Phase 5: Add simulation tables for backtesting
-- Rollback: DROP TABLE IF EXISTS simulation_metrics; DROP TABLE IF EXISTS simulation_transactions; DROP TABLE IF EXISTS simulations;

CREATE TABLE IF NOT EXISTS simulations (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    asset_symbol VARCHAR(20) NOT NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    initial_wallet NUMERIC(18, 2) NOT NULL,
    parameters JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS simulation_transactions (
    id BIGSERIAL PRIMARY KEY,
    simulation_id BIGINT NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    action VARCHAR(4) NOT NULL CHECK (action IN ('BUY', 'SELL')),
    quantity NUMERIC(24, 12) NOT NULL,
    unit_price NUMERIC(18, 2) NOT NULL,
    fee NUMERIC(18, 2) NOT NULL DEFAULT 0,
    paired_buy_id BIGINT NULL REFERENCES simulation_transactions(id),
    realized_pnl NUMERIC(18, 2) NULL,
    trigger_rule TEXT NOT NULL,
    simulated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS simulation_metrics (
    simulation_id BIGINT PRIMARY KEY REFERENCES simulations(id) ON DELETE CASCADE,
    total_buys INT NOT NULL,
    total_sells INT NOT NULL,
    realized_pnl NUMERIC(18, 2) NOT NULL,
    unrealized_pnl_at_end NUMERIC(18, 2) NOT NULL,
    total_return_pct NUMERIC(10, 4) NOT NULL,
    win_rate_pct NUMERIC(10, 4) NOT NULL,
    crash_guard_activations INT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_simulations_name ON simulations(name);
CREATE INDEX IF NOT EXISTS idx_simulations_asset ON simulations(asset_symbol);
CREATE INDEX IF NOT EXISTS idx_simulation_transactions_simulation_id ON simulation_transactions(simulation_id);
CREATE INDEX IF NOT EXISTS idx_simulation_transactions_action ON simulation_transactions(action);
CREATE INDEX IF NOT EXISTS idx_simulation_transactions_simulated_at ON simulation_transactions(simulated_at);
