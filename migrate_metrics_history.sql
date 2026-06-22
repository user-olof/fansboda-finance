-- Restore one row per (ticker, trading_date) for historical metrics.
-- Run once in the Neon SQL editor before backfill_sma.py.

ALTER TABLE metrics DROP CONSTRAINT IF EXISTS metrics_ticker_key;

ALTER TABLE metrics
    ADD CONSTRAINT metrics_ticker_trading_date_key UNIQUE (ticker, trading_date);

CREATE INDEX IF NOT EXISTS idx_metrics_trading_date ON metrics (trading_date);
