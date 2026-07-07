-- Verify fansboda-finance data model (RFC-001).
-- Expect one row per check; empty result or ERROR means schema drift.

-- tickers table exists with symbol PK and updated_at
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'tickers'
ORDER BY ordinal_position;

SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'tickers'
  AND column_name = 'updated_at';

-- metrics columns and numeric precision
SELECT column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'metrics'
ORDER BY ordinal_position;

SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'tickers'
  AND column_name IN ('sector', 'industry', 'company')
ORDER BY column_name;
-- expect 3 rows after migrate_rename_name_to_company.sql or fresh schema.sql

SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'metrics'
  AND column_name IN ('currency', 'company', 'raw_50', 'raw_200')
ORDER BY column_name;
-- expect 4 rows after migrate_add_raw_ratios_and_market.sql or fresh schema.sql

-- market table and columns
SELECT column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'market'
ORDER BY ordinal_position;

SELECT conname
FROM pg_constraint
WHERE conrelid = 'public.market'::regclass
  AND contype = 'p'
  AND conname = 'market_pkey';

-- unique (ticker, trading_date)
SELECT conname
FROM pg_constraint
WHERE conrelid = 'public.metrics'::regclass
  AND contype = 'u'
  AND conname = 'metrics_ticker_trading_date_key';

-- FK metrics.ticker -> tickers.symbol ON DELETE CASCADE
SELECT conname, confdeltype
FROM pg_constraint
WHERE conrelid = 'public.metrics'::regclass
  AND contype = 'f'
  AND conname = 'metrics_ticker_fkey';
-- confdeltype 'c' = CASCADE

-- index for retention purge
SELECT indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'metrics'
  AND indexname = 'idx_metrics_trading_date';
