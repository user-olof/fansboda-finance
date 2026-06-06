CREATE TABLE IF NOT EXISTS metrics (
    id             BIGSERIAL   PRIMARY KEY,
    ticker         TEXT        NOT NULL,
    trading_date DATE        NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL,
    sma_50         NUMERIC(18, 6),
    sma_200        NUMERIC(18, 6),
    UNIQUE (ticker, trading_date)
);
