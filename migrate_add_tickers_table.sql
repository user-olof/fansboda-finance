-- Migrate to tickers reference table with FK from metrics.
-- Run once in the Neon SQL editor before deploying the updated code.

-- 1. Create the tickers watchlist table.
CREATE TABLE IF NOT EXISTS tickers (
    symbol  TEXT PRIMARY KEY,
    name    TEXT
);

-- 2. Seed tickers from existing metrics rows.
INSERT INTO tickers (symbol)
SELECT DISTINCT ticker FROM metrics
ON CONFLICT (symbol) DO NOTHING;

-- 3. Add company name column to metrics.
ALTER TABLE metrics
ADD COLUMN IF NOT EXISTS name TEXT;

-- 4. Enforce FK: metrics.ticker must exist in tickers.
ALTER TABLE metrics
ADD CONSTRAINT metrics_ticker_fkey
FOREIGN KEY (ticker) REFERENCES tickers(symbol) ON DELETE CASCADE;

-- 5. Backfill metrics.name from tickers where available.
UPDATE metrics AS m
SET name = t.name
FROM tickers AS t
WHERE m.ticker = t.symbol
  AND t.name IS NOT NULL;
