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
