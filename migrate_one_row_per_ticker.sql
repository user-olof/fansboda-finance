-- Migrate existing metrics table from one row per (ticker, trading_date)
-- to one row per ticker. Run once in the Neon SQL editor before deploying
-- the updated fetch_sma.py.

-- 1. Remove duplicate rows, keeping the latest trading_date per ticker.
DELETE FROM metrics
WHERE id NOT IN (
    SELECT DISTINCT ON (ticker) id
    FROM metrics
    ORDER BY ticker, trading_date DESC, updated_at DESC, id DESC
);

-- 2. Drop the old composite unique constraint.
ALTER TABLE metrics DROP CONSTRAINT IF EXISTS metrics_ticker_trading_date_key;

-- 3. Enforce one row per ticker.
ALTER TABLE metrics ADD CONSTRAINT metrics_ticker_key UNIQUE (ticker);
