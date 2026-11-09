-- Step 25: per-stock lookup indexes on the metrics tables (specs/009-metrics-ticker-index).
-- Adds (ticker, trading_date) to us_metrics / swe_metrics / uk_metrics so lookups
-- by stock symbol stop reading the whole table. No row changes.
-- Safe to repeat; repairs an index left invalid by an interrupted build.
-- Run with psql outside a transaction (no -1 / --single-transaction): CONCURRENTLY
-- builds do not block reads or writes but cannot run in a transaction block.
-- On Neon use the direct (non-pooler) endpoint.

SELECT format('DROP INDEX CONCURRENTLY IF EXISTS %I', c.relname)
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE NOT i.indisvalid
  AND c.relname IN (
    'idx_us_metrics_ticker_trading_date',
    'idx_swe_metrics_ticker_trading_date',
    'idx_uk_metrics_ticker_trading_date'
  )
\gexec

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_us_metrics_ticker_trading_date ON us_metrics (ticker, trading_date);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_swe_metrics_ticker_trading_date ON swe_metrics (ticker, trading_date);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_uk_metrics_ticker_trading_date ON uk_metrics (ticker, trading_date);
