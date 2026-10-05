-- Verify fansboda-finance data model (RFC-001 country sets).
-- Expect one row per check; empty result or ERROR means schema drift.

-- us_tickers / swe_tickers / uk_tickers columns
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('us_tickers', 'swe_tickers', 'uk_tickers')
ORDER BY table_name, ordinal_position;

SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('us_tickers', 'swe_tickers', 'uk_tickers')
  AND column_name IN (
    'sector', 'industry', 'company', 'market', 'exchange_name',
    'business_summary', 'updated_at'
  )
ORDER BY table_name, column_name;
-- expect 21 rows (7 columns × 3 tables)

-- us_metrics / swe_metrics / uk_metrics columns and numeric precision
SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('us_metrics', 'swe_metrics', 'uk_metrics')
ORDER BY table_name, ordinal_position;

SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('us_metrics', 'swe_metrics', 'uk_metrics')
  AND column_name IN ('currency', 'company', 'momentum', 'z_score', 'week_start')
ORDER BY table_name, column_name;
-- expect 15 rows

-- weekly growth columns (step 20, FR-5a)
SELECT table_name, column_name, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('us_metrics', 'swe_metrics', 'uk_metrics')
  AND column_name IN ('price_growth', 'sma_50_growth', 'sma_200_growth')
ORDER BY table_name, column_name;
-- expect 9 rows (18, 6)

-- us_market_metrics / swe_market_metrics / uk_market_metrics
SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
    'us_market_metrics', 'swe_market_metrics', 'uk_market_metrics'
  )
ORDER BY table_name, ordinal_position;

SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
    'us_market_metrics', 'swe_market_metrics', 'uk_market_metrics'
  )
  AND column_name IN ('week_start', 'momentum_mean', 'momentum_std')
ORDER BY table_name, column_name;
-- expect 9 rows

SELECT c.conrelid::regclass AS table_name, c.conname
FROM pg_constraint c
WHERE c.conrelid IN (
    'public.us_market_metrics'::regclass,
    'public.swe_market_metrics'::regclass,
    'public.uk_market_metrics'::regclass
  )
  AND c.contype = 'p'
ORDER BY 1;

-- *_by_sector must be gone after step 22 / fresh schema (RFC-018)
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('us_by_sector', 'swe_by_sector', 'uk_by_sector');
-- expect 0 rows

-- indices (steps 18–19 v2 shape + step 21 sector columns)
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'indices'
ORDER BY ordinal_position;
-- expect 13 rows in this order: ticker, sector (NOT NULL, index label — name
-- merged into it by step 21), country, trading_date, updated_at,
-- ticker_count, current_price, sma_50, sma_200, momentum, currency,
-- pct_uptrend, z_score (no week_start, no name)

SELECT c.conname
FROM pg_constraint c
WHERE c.conrelid = 'public.indices'::regclass
  AND c.contype = 'p';

-- unique (week_start, ticker): one row per ticker per calendar week
SELECT c.conrelid::regclass AS table_name, c.conname
FROM pg_constraint c
WHERE c.conrelid IN (
    'public.us_metrics'::regclass,
    'public.swe_metrics'::regclass,
    'public.uk_metrics'::regclass
  )
  AND c.contype = 'u'
  AND c.conname LIKE '%_metrics_week_start_ticker_key'
ORDER BY 1;
-- expect 3 rows

-- FK metrics.ticker -> tickers.symbol ON DELETE CASCADE
SELECT c.conrelid::regclass AS table_name, c.conname, c.confdeltype
FROM pg_constraint c
WHERE c.conrelid IN (
    'public.us_metrics'::regclass,
    'public.swe_metrics'::regclass,
    'public.uk_metrics'::regclass
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
    'idx_uk_metrics_trading_date'
  )
ORDER BY tablename, indexname;

-- legacy single-set tables must be gone after step 11 / fresh schema
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('tickers', 'metrics', 'market_metrics', 'market');
-- expect 0 rows
