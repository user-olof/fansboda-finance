-- Step 15: bucket metrics by calendar week (PRD §6).
-- *_metrics: add week_start (Monday of trading_date), keep only the latest bar
-- per (ticker, week_start), and replace UNIQUE (ticker, trading_date) with
-- UNIQUE (week_start, ticker).
-- *_market_metrics: re-key on (market, week_start). The tables hold derived
-- aggregates only, so they are recreated empty; run backfill_market.py after.
-- Idempotent: each table is skipped once it already has week_start.

DO $$
DECLARE
    prefix TEXT;
BEGIN
    FOREACH prefix IN ARRAY ARRAY['us', 'swe', 'uk'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = prefix || '_metrics'
              AND column_name = 'week_start'
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I ADD COLUMN week_start DATE',
                prefix || '_metrics'
            );
            EXECUTE format(
                'UPDATE %I SET week_start = date_trunc(''week'', trading_date)::date',
                prefix || '_metrics'
            );
            EXECUTE format(
                'DELETE FROM %1$I older USING %1$I newer
                 WHERE older.ticker = newer.ticker
                   AND older.week_start = newer.week_start
                   AND older.trading_date < newer.trading_date',
                prefix || '_metrics'
            );
            EXECUTE format(
                'ALTER TABLE %I ALTER COLUMN week_start SET NOT NULL',
                prefix || '_metrics'
            );
            EXECUTE format(
                'ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I',
                prefix || '_metrics',
                prefix || '_metrics_ticker_trading_date_key'
            );
            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I UNIQUE (week_start, ticker)',
                prefix || '_metrics',
                prefix || '_metrics_week_start_ticker_key'
            );
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = prefix || '_market_metrics'
              AND column_name = 'trading_date'
        ) THEN
            EXECUTE format('DROP TABLE %I', prefix || '_market_metrics');
            EXECUTE format(
                'CREATE TABLE %I (
                    market          TEXT            NOT NULL,
                    week_start      DATE            NOT NULL,
                    updated_at      TIMESTAMPTZ     NOT NULL,
                    momentum_mean   NUMERIC(18, 6),
                    momentum_std    NUMERIC(18, 6),
                    PRIMARY KEY (market, week_start)
                )',
                prefix || '_market_metrics'
            );
        END IF;
    END LOOP;
END $$;
