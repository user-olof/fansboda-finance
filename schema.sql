-- fansboda-finance schema (RFC-001)
-- Run once on a new Neon database. See project-docs/MIGRATIONS.md for upgrades.
-- Country-partitioned table sets (PRD §6): US (us_*) and Swedish (swe_*).

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
