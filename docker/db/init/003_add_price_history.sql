CREATE TABLE IF NOT EXISTS price_samples (
    id BIGSERIAL PRIMARY KEY,
    asset_symbol VARCHAR(20) NOT NULL,
    source VARCHAR(20) NOT NULL,
    price_usd NUMERIC(18, 2) NOT NULL CHECK (price_usd > 0),
    sampled_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (asset_symbol, source, sampled_at)
);

CREATE INDEX IF NOT EXISTS idx_price_samples_symbol_sampled
ON price_samples (asset_symbol, sampled_at DESC);
