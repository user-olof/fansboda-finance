-- Add normalized SMA ratio columns and market aggregates table (RFC-001).
-- Idempotent for existing databases that already ran prior migrations.

ALTER TABLE metrics
    ADD COLUMN IF NOT EXISTS raw_50 NUMERIC(18, 6);

ALTER TABLE metrics
    ADD COLUMN IF NOT EXISTS raw_200 NUMERIC(18, 6);

CREATE TABLE IF NOT EXISTS market (
    trading_date    DATE            PRIMARY KEY,
    updated_at      TIMESTAMPTZ     NOT NULL,
    raw_mean_50     NUMERIC(18, 6),
    raw_mean_200    NUMERIC(18, 6),
    raw_std_50      NUMERIC(18, 6),
    raw_std_200     NUMERIC(18, 6)
);
