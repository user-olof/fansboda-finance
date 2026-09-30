-- fansboda-finance schema (RFC-001)
-- Run once on a new Neon database. See project-docs/MIGRATIONS.md for upgrades.
-- Country-partitioned table sets (PRD §6): US (us_*), Swedish (swe_*), UK (uk_*).
-- Metrics hold one row per ticker per calendar week (week_start = Monday);
-- trading_date is the actual bar date within that week.
-- *_by_sector holds equal-weighted weekly trend averages per tickers.sector.

-- ---------------------------------------------------------------------------
-- US stocks
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS us_tickers (
    symbol         TEXT PRIMARY KEY,
    company        TEXT,
    sector         TEXT,
    industry       TEXT,
    market         TEXT,
    exchange_name  TEXT,
    business_summary TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS us_metrics (
    id             BIGSERIAL       PRIMARY KEY,
    ticker         TEXT            NOT NULL
                       REFERENCES us_tickers (symbol) ON DELETE CASCADE,
    company        TEXT,
    week_start     DATE            NOT NULL,
    trading_date   DATE            NOT NULL,
    updated_at     TIMESTAMPTZ     NOT NULL,
    currency       TEXT,
    sma_50         NUMERIC(18, 6),
    sma_200        NUMERIC(18, 6),
    current_price  NUMERIC(18, 6),
    momentum       NUMERIC(18, 6),
    z_score        NUMERIC(18, 6),
    CONSTRAINT us_metrics_week_start_ticker_key UNIQUE (week_start, ticker)
);

CREATE INDEX IF NOT EXISTS idx_us_metrics_trading_date ON us_metrics (trading_date);

CREATE TABLE IF NOT EXISTS us_market_metrics (
    market          TEXT            NOT NULL,
    week_start      DATE            NOT NULL,
    updated_at      TIMESTAMPTZ     NOT NULL,
    momentum_mean   NUMERIC(18, 6),
    momentum_std    NUMERIC(18, 6),
    PRIMARY KEY (market, week_start)
);

CREATE TABLE IF NOT EXISTS us_by_sector (
    sector           TEXT            NOT NULL,
    week_start       DATE            NOT NULL,
    updated_at       TIMESTAMPTZ     NOT NULL,
    ticker_count     INTEGER         NOT NULL,
    momentum_mean    NUMERIC(18, 6),
    momentum_median  NUMERIC(18, 6),
    z_score_mean     NUMERIC(18, 6),
    pct_uptrend      NUMERIC(18, 6),
    PRIMARY KEY (sector, week_start)
);

-- ---------------------------------------------------------------------------
-- Swedish stocks
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swe_tickers (
    symbol         TEXT PRIMARY KEY,
    company        TEXT,
    sector         TEXT,
    industry       TEXT,
    market         TEXT,
    exchange_name  TEXT,
    business_summary TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS swe_metrics (
    id             BIGSERIAL       PRIMARY KEY,
    ticker         TEXT            NOT NULL
                       REFERENCES swe_tickers (symbol) ON DELETE CASCADE,
    company        TEXT,
    week_start     DATE            NOT NULL,
    trading_date   DATE            NOT NULL,
    updated_at     TIMESTAMPTZ     NOT NULL,
    currency       TEXT,
    sma_50         NUMERIC(18, 6),
    sma_200        NUMERIC(18, 6),
    current_price  NUMERIC(18, 6),
    momentum       NUMERIC(18, 6),
    z_score        NUMERIC(18, 6),
    CONSTRAINT swe_metrics_week_start_ticker_key UNIQUE (week_start, ticker)
);

CREATE INDEX IF NOT EXISTS idx_swe_metrics_trading_date ON swe_metrics (trading_date);

CREATE TABLE IF NOT EXISTS swe_market_metrics (
    market          TEXT            NOT NULL,
    week_start      DATE            NOT NULL,
    updated_at      TIMESTAMPTZ     NOT NULL,
    momentum_mean   NUMERIC(18, 6),
    momentum_std    NUMERIC(18, 6),
    PRIMARY KEY (market, week_start)
);

CREATE TABLE IF NOT EXISTS swe_by_sector (
    sector           TEXT            NOT NULL,
    week_start       DATE            NOT NULL,
    updated_at       TIMESTAMPTZ     NOT NULL,
    ticker_count     INTEGER         NOT NULL,
    momentum_mean    NUMERIC(18, 6),
    momentum_median  NUMERIC(18, 6),
    z_score_mean     NUMERIC(18, 6),
    pct_uptrend      NUMERIC(18, 6),
    PRIMARY KEY (sector, week_start)
);

-- ---------------------------------------------------------------------------
-- UK stocks
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS uk_tickers (
    symbol         TEXT PRIMARY KEY,
    company        TEXT,
    sector         TEXT,
    industry       TEXT,
    market         TEXT,
    exchange_name  TEXT,
    business_summary TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS uk_metrics (
    id             BIGSERIAL       PRIMARY KEY,
    ticker         TEXT            NOT NULL
                       REFERENCES uk_tickers (symbol) ON DELETE CASCADE,
    company        TEXT,
    week_start     DATE            NOT NULL,
    trading_date   DATE            NOT NULL,
    updated_at     TIMESTAMPTZ     NOT NULL,
    currency       TEXT,
    sma_50         NUMERIC(18, 6),
    sma_200        NUMERIC(18, 6),
    current_price  NUMERIC(18, 6),
    momentum       NUMERIC(18, 6),
    z_score        NUMERIC(18, 6),
    CONSTRAINT uk_metrics_week_start_ticker_key UNIQUE (week_start, ticker)
);

CREATE INDEX IF NOT EXISTS idx_uk_metrics_trading_date ON uk_metrics (trading_date);

CREATE TABLE IF NOT EXISTS uk_market_metrics (
    market          TEXT            NOT NULL,
    week_start      DATE            NOT NULL,
    updated_at      TIMESTAMPTZ     NOT NULL,
    momentum_mean   NUMERIC(18, 6),
    momentum_std    NUMERIC(18, 6),
    PRIMARY KEY (market, week_start)
);

CREATE TABLE IF NOT EXISTS uk_by_sector (
    sector           TEXT            NOT NULL,
    week_start       DATE            NOT NULL,
    updated_at       TIMESTAMPTZ     NOT NULL,
    ticker_count     INTEGER         NOT NULL,
    momentum_mean    NUMERIC(18, 6),
    momentum_median  NUMERIC(18, 6),
    z_score_mean     NUMERIC(18, 6),
    pct_uptrend      NUMERIC(18, 6),
    PRIMARY KEY (sector, week_start)
);
