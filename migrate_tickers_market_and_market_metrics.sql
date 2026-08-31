-- Add tickers.market and replace legacy watchlist-wide market table with
-- market_metrics (one row per listing market per trading_date). RFC-001 step 10.
-- Idempotent: safe to re-run. Recompute aggregates with backfill_market.py.

ALTER TABLE tickers
    ADD COLUMN IF NOT EXISTS market TEXT;

CREATE TABLE IF NOT EXISTS market_metrics (
    market          TEXT            NOT NULL,
    trading_date    DATE            NOT NULL,
    updated_at      TIMESTAMPTZ     NOT NULL,
    raw_mean_50     NUMERIC(18, 6),
    raw_mean_200    NUMERIC(18, 6),
    raw_std_50      NUMERIC(18, 6),
    raw_std_200     NUMERIC(18, 6),
    PRIMARY KEY (market, trading_date)
);

-- Legacy step-9 table: one aggregate row per trading_date (watchlist-wide).
DROP TABLE IF EXISTS market;

CREATE INDEX IF NOT EXISTS idx_market_metrics_trading_date ON market_metrics (trading_date);
