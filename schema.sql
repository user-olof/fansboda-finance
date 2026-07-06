-- fansboda-finance schema (RFC-001)
-- Run once on a new Neon database. See project-docs/MIGRATIONS.md for upgrades.

CREATE TABLE IF NOT EXISTS tickers (
    symbol      TEXT PRIMARY KEY,
    company     TEXT,
    sector      TEXT,
    industry    TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS metrics (
    id             BIGSERIAL       PRIMARY KEY,
    ticker         TEXT            NOT NULL
                       REFERENCES tickers (symbol) ON DELETE CASCADE,
    company        TEXT,
    trading_date   DATE            NOT NULL,
    updated_at     TIMESTAMPTZ     NOT NULL,
    currency       TEXT,
    sma_50         NUMERIC(18, 6),
    sma_200        NUMERIC(18, 6),
    current_price  NUMERIC(18, 6),
    CONSTRAINT metrics_ticker_trading_date_key UNIQUE (ticker, trading_date)
);

-- Retention purge: DELETE FROM metrics WHERE trading_date < cutoff
CREATE INDEX IF NOT EXISTS idx_metrics_trading_date ON metrics (trading_date);
