-- Step 13: create UK country table set (PRD §6 / RFC-001).
-- Idempotent CREATE IF NOT EXISTS.
-- Moves existing .L / uk_market rows from us_* into uk_* when present.

CREATE TABLE IF NOT EXISTS uk_tickers (
    symbol         TEXT PRIMARY KEY,
    company        TEXT,
    sector         TEXT,
    industry       TEXT,
    market         TEXT,
    exchange_name  TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS uk_metrics (
    id             BIGSERIAL       PRIMARY KEY,
    ticker         TEXT            NOT NULL
                       REFERENCES uk_tickers (symbol) ON DELETE CASCADE,
    company        TEXT,
    trading_date   DATE            NOT NULL,
    updated_at     TIMESTAMPTZ     NOT NULL,
    currency       TEXT,
    sma_50         NUMERIC(18, 6),
    sma_200        NUMERIC(18, 6),
    current_price  NUMERIC(18, 6),
    raw_50         NUMERIC(18, 6),
    raw_200        NUMERIC(18, 6),
    CONSTRAINT uk_metrics_ticker_trading_date_key UNIQUE (ticker, trading_date)
);

CREATE INDEX IF NOT EXISTS idx_uk_metrics_trading_date ON uk_metrics (trading_date);

CREATE TABLE IF NOT EXISTS uk_market_metrics (
    market          TEXT            NOT NULL,
    trading_date    DATE            NOT NULL,
    updated_at      TIMESTAMPTZ     NOT NULL,
    raw_mean_50     NUMERIC(18, 6),
    raw_mean_200    NUMERIC(18, 6),
    raw_std_50      NUMERIC(18, 6),
    raw_std_200     NUMERIC(18, 6),
    PRIMARY KEY (market, trading_date)
);

CREATE INDEX IF NOT EXISTS idx_uk_market_metrics_trading_date
    ON uk_market_metrics (trading_date);

-- Ensure exchange_name exists on uk_tickers (no-op if step 12 already ran after this)
ALTER TABLE uk_tickers
    ADD COLUMN IF NOT EXISTS exchange_name TEXT;

-- Move UK listings that landed in us_* before UK tables existed
DO $$
BEGIN
    IF to_regclass('public.us_tickers') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'us_tickers'
              AND column_name = 'exchange_name'
        ) THEN
            INSERT INTO uk_tickers (
                symbol, company, sector, industry, market, exchange_name, updated_at
            )
            SELECT
                symbol, company, sector, industry, market, exchange_name, updated_at
            FROM us_tickers
            WHERE market = 'uk_market' OR symbol LIKE '%.L'
            ON CONFLICT (symbol) DO NOTHING;
        ELSE
            INSERT INTO uk_tickers (
                symbol, company, sector, industry, market, updated_at
            )
            SELECT
                symbol, company, sector, industry, market, updated_at
            FROM us_tickers
            WHERE market = 'uk_market' OR symbol LIKE '%.L'
            ON CONFLICT (symbol) DO NOTHING;
        END IF;
    END IF;

    IF to_regclass('public.us_metrics') IS NOT NULL THEN
        INSERT INTO uk_metrics (
            ticker, company, trading_date, updated_at, currency,
            sma_50, sma_200, current_price, raw_50, raw_200
        )
        SELECT
            m.ticker, m.company, m.trading_date, m.updated_at, m.currency,
            m.sma_50, m.sma_200, m.current_price, m.raw_50, m.raw_200
        FROM us_metrics m
        WHERE m.ticker IN (SELECT symbol FROM uk_tickers)
        ON CONFLICT (ticker, trading_date) DO NOTHING;
    END IF;

    IF to_regclass('public.us_market_metrics') IS NOT NULL THEN
        INSERT INTO uk_market_metrics (
            market, trading_date, updated_at,
            raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
        )
        SELECT
            market, trading_date, updated_at,
            raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
        FROM us_market_metrics
        WHERE market = 'uk_market'
        ON CONFLICT (market, trading_date) DO NOTHING;
    END IF;

    IF to_regclass('public.us_tickers') IS NOT NULL THEN
        DELETE FROM us_metrics
        WHERE ticker IN (SELECT symbol FROM uk_tickers);

        DELETE FROM us_market_metrics
        WHERE market = 'uk_market';

        DELETE FROM us_tickers
        WHERE market = 'uk_market' OR symbol LIKE '%.L';
    END IF;
END $$;
