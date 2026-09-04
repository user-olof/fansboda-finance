-- Verify fansboda-finance data model (RFC-001 country sets).
-- Expect one row per check; empty result or ERROR means schema drift.

-- us_tickers / swe_tickers columns
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('us_tickers', 'swe_tickers')
ORDER BY table_name, ordinal_position;

SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('us_tickers', 'swe_tickers')
  AND column_name IN ('sector', 'industry', 'company', 'market', 'updated_at')
ORDER BY table_name, column_name;
-- expect 10 rows (5 columns × 2 tables)

-- us_metrics / swe_metrics columns and numeric precision
SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('us_metrics', 'swe_metrics')
ORDER BY table_name, ordinal_position;

SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('us_metrics', 'swe_metrics')
  AND column_name IN ('currency', 'company', 'raw_50', 'raw_200')
ORDER BY table_name, column_name;
-- expect 8 rows

-- us_market_metrics / swe_market_metrics
SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('us_market_metrics', 'swe_market_metrics')
ORDER BY table_name, ordinal_position;

SELECT c.conrelid::regclass AS table_name, c.conname
FROM pg_constraint c
WHERE c.conrelid IN (
    'public.us_market_metrics'::regclass,
    'public.swe_market_metrics'::regclass
  )
  AND c.contype = 'p'
ORDER BY 1;

-- unique (ticker, trading_date)
SELECT c.conrelid::regclass AS table_name, c.conname
FROM pg_constraint c
WHERE c.conrelid IN (
    'public.us_metrics'::regclass,
    'public.swe_metrics'::regclass
  )
  AND c.contype = 'u'
  AND c.conname LIKE '%_ticker_trading_date_key'
ORDER BY 1;

-- FK metrics.ticker -> tickers.symbol ON DELETE CASCADE
SELECT c.conrelid::regclass AS table_name, c.conname, c.confdeltype
FROM pg_constraint c
WHERE c.conrelid IN (
    'public.us_metrics'::regclass,
    'public.swe_metrics'::regclass
  )
  AND c.contype = 'f'
ORDER BY 1;
-- confdeltype 'c' = CASCADE

-- indexes for retention purge
SELECT tablename, indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN (
    'idx_us_metrics_trading_date',
    'idx_swe_metrics_trading_date',
    'idx_us_market_metrics_trading_date',
    'idx_swe_market_metrics_trading_date'
  )
ORDER BY tablename, indexname;

-- legacy single-set tables must be gone after step 11 / fresh schema
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('tickers', 'metrics', 'market_metrics', 'market');
-- expect 0 rows
