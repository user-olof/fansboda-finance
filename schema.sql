CREATE TABLE IF NOT EXISTS tickers (
    symbol  TEXT PRIMARY KEY,
    name    TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id             BIGSERIAL   PRIMARY KEY,
    ticker         TEXT        NOT NULL UNIQUE
                       REFERENCES tickers(symbol) ON DELETE CASCADE,
    name           TEXT,
    trading_date   DATE        NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL,
    sma_50         NUMERIC(18, 6),
    sma_200        NUMERIC(18, 6),
    current_price  NUMERIC(18, 6)
);
