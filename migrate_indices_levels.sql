-- Step 19: indices v2 — price / SMA-50 / SMA-200 levels + momentum keyed by
-- trading_date (PRD §5.8 / RFC-015). Replaces the v1 table (week_start,
-- avg_return, index_price); index rows are derived, so they are dropped and
-- rebuilt afterwards with:
--   pipenv run python compute_indices.py
-- No-op once applied.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'indices'
          AND column_name = 'week_start'
    ) THEN
        DROP TABLE indices;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS indices (
    ticker         TEXT            NOT NULL,
    name           TEXT            NOT NULL,
    country        TEXT            NOT NULL,
    trading_date   DATE            NOT NULL,
    updated_at     TIMESTAMPTZ     NOT NULL,
    ticker_count   INTEGER         NOT NULL,
    current_price  NUMERIC(18, 6)  NOT NULL,
    sma_50         NUMERIC(18, 6)  NOT NULL,
    sma_200        NUMERIC(18, 6)  NOT NULL,
    momentum       NUMERIC(18, 6),
    PRIMARY KEY (ticker, trading_date)
);
