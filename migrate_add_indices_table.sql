-- Step 18: equal-weighted weekly country indices (PRD §5.8 / RFC-015).
-- Idempotent. Build history after applying with:
--   pipenv run python compute_indices.py

CREATE TABLE IF NOT EXISTS indices (
    ticker        TEXT            NOT NULL,
    name          TEXT            NOT NULL,
    country       TEXT            NOT NULL,
    week_start    DATE            NOT NULL,
    updated_at    TIMESTAMPTZ     NOT NULL,
    ticker_count  INTEGER         NOT NULL,
    avg_return    NUMERIC(18, 6),
    index_price   NUMERIC(18, 6)  NOT NULL,
    PRIMARY KEY (ticker, week_start)
);
