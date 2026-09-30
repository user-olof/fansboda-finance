-- Step 17: weekly equal-weighted trend averages per sector (PRD §5.7 / §6).
-- Idempotent. Populate after applying with:
--   pipenv run python compute_sector_trends.py

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
