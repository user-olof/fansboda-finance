-- Split legacy single-set tables into US / Swedish country sets (RFC-001 step 11).
-- Idempotent: creates us_*/swe_* tables, copies from legacy when present, drops legacy.
-- Routing: market = 'se_market' or symbol LIKE '%.ST' → swe_*; otherwise → us_*.

-- ---------------------------------------------------------------------------
-- US stocks
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS us_tickers (
    symbol      TEXT PRIMARY KEY,
    company     TEXT,
    sector      TEXT,
    industry    TEXT,
    market      TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS us_metrics (
    id             BIGSERIAL       PRIMARY KEY,
    ticker         TEXT            NOT NULL
                       REFERENCES us_tickers (symbol) ON DELETE CASCADE,
    company        TEXT,
    trading_date   DATE            NOT NULL,
    updated_at     TIMESTAMPTZ     NOT NULL,
    currency       TEXT,
    sma_50         NUMERIC(18, 6),
    sma_200        NUMERIC(18, 6),
    current_price  NUMERIC(18, 6),
    raw_50         NUMERIC(18, 6),
    raw_200        NUMERIC(18, 6),
    CONSTRAINT us_metrics_ticker_trading_date_key UNIQUE (ticker, trading_date)
);

CREATE INDEX IF NOT EXISTS idx_us_metrics_trading_date ON us_metrics (trading_date);

CREATE TABLE IF NOT EXISTS us_market_metrics (
    market          TEXT            NOT NULL,
    trading_date    DATE            NOT NULL,
    updated_at      TIMESTAMPTZ     NOT NULL,
    raw_mean_50     NUMERIC(18, 6),
    raw_mean_200    NUMERIC(18, 6),
    raw_std_50      NUMERIC(18, 6),
    raw_std_200     NUMERIC(18, 6),
    PRIMARY KEY (market, trading_date)
);

CREATE INDEX IF NOT EXISTS idx_us_market_metrics_trading_date
    ON us_market_metrics (trading_date);

-- ---------------------------------------------------------------------------
-- Swedish stocks
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swe_tickers (
    symbol      TEXT PRIMARY KEY,
    company     TEXT,
    sector      TEXT,
    industry    TEXT,
    market      TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS swe_metrics (
    id             BIGSERIAL       PRIMARY KEY,
    ticker         TEXT            NOT NULL
                       REFERENCES swe_tickers (symbol) ON DELETE CASCADE,
    company        TEXT,
    trading_date   DATE            NOT NULL,
    updated_at     TIMESTAMPTZ     NOT NULL,
    currency       TEXT,
    sma_50         NUMERIC(18, 6),
    sma_200        NUMERIC(18, 6),
    current_price  NUMERIC(18, 6),
    raw_50         NUMERIC(18, 6),
    raw_200        NUMERIC(18, 6),
    CONSTRAINT swe_metrics_ticker_trading_date_key UNIQUE (ticker, trading_date)
);

CREATE INDEX IF NOT EXISTS idx_swe_metrics_trading_date ON swe_metrics (trading_date);

CREATE TABLE IF NOT EXISTS swe_market_metrics (
    market          TEXT            NOT NULL,
    trading_date    DATE            NOT NULL,
    updated_at      TIMESTAMPTZ     NOT NULL,
    raw_mean_50     NUMERIC(18, 6),
    raw_mean_200    NUMERIC(18, 6),
    raw_std_50      NUMERIC(18, 6),
    raw_std_200     NUMERIC(18, 6),
    PRIMARY KEY (market, trading_date)
);

CREATE INDEX IF NOT EXISTS idx_swe_market_metrics_trading_date
    ON swe_market_metrics (trading_date);

-- ---------------------------------------------------------------------------
-- Copy from legacy single-set tables when present
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF to_regclass('public.tickers') IS NOT NULL THEN
        INSERT INTO swe_tickers (symbol, company, sector, industry, market, updated_at)
        SELECT symbol, company, sector, industry, market, updated_at
        FROM tickers
        WHERE market = 'se_market' OR symbol LIKE '%.ST'
        ON CONFLICT (symbol) DO NOTHING;

        INSERT INTO us_tickers (symbol, company, sector, industry, market, updated_at)
        SELECT symbol, company, sector, industry, market, updated_at
        FROM tickers
        WHERE NOT (market = 'se_market' OR symbol LIKE '%.ST')
        ON CONFLICT (symbol) DO NOTHING;
    END IF;

    IF to_regclass('public.metrics') IS NOT NULL THEN
        INSERT INTO swe_metrics (
            ticker, company, trading_date, updated_at, currency,
            sma_50, sma_200, current_price, raw_50, raw_200
        )
        SELECT
            m.ticker, m.company, m.trading_date, m.updated_at, m.currency,
            m.sma_50, m.sma_200, m.current_price, m.raw_50, m.raw_200
        FROM metrics m
        WHERE m.ticker IN (SELECT symbol FROM swe_tickers)
        ON CONFLICT (ticker, trading_date) DO NOTHING;

        INSERT INTO us_metrics (
            ticker, company, trading_date, updated_at, currency,
            sma_50, sma_200, current_price, raw_50, raw_200
        )
        SELECT
            m.ticker, m.company, m.trading_date, m.updated_at, m.currency,
            m.sma_50, m.sma_200, m.current_price, m.raw_50, m.raw_200
        FROM metrics m
        WHERE m.ticker IN (SELECT symbol FROM us_tickers)
        ON CONFLICT (ticker, trading_date) DO NOTHING;
    END IF;

    IF to_regclass('public.market_metrics') IS NOT NULL THEN
        INSERT INTO swe_market_metrics (
            market, trading_date, updated_at,
            raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
        )
        SELECT
            market, trading_date, updated_at,
            raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
        FROM market_metrics
        WHERE market = 'se_market'
        ON CONFLICT (market, trading_date) DO NOTHING;

        INSERT INTO us_market_metrics (
            market, trading_date, updated_at,
            raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
        )
        SELECT
            market, trading_date, updated_at,
            raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
        FROM market_metrics
        WHERE market IS DISTINCT FROM 'se_market'
        ON CONFLICT (market, trading_date) DO NOTHING;
    END IF;
END $$;

DROP TABLE IF EXISTS metrics CASCADE;
DROP TABLE IF EXISTS market_metrics CASCADE;
DROP TABLE IF EXISTS tickers CASCADE;
