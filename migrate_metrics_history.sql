-- Restore one row per (ticker, trading_date) for historical metrics.
-- Run once in the Neon SQL editor before backfill_sma.py.

ALTER TABLE metrics DROP CONSTRAINT IF EXISTS metrics_ticker_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'metrics_ticker_trading_date_key'
          AND conrelid = 'public.metrics'::regclass
    ) THEN
        ALTER TABLE metrics
            ADD CONSTRAINT metrics_ticker_trading_date_key UNIQUE (ticker, trading_date);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_metrics_trading_date ON metrics (trading_date);
