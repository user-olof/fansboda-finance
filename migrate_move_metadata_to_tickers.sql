-- Align metadata columns with PRD §6 (RFC-001):
--   sector, industry on tickers; currency on metrics.
-- Supersedes migrate_add_metrics_metadata.sql. Safe to re-run.

ALTER TABLE tickers
    ADD COLUMN IF NOT EXISTS sector TEXT;

ALTER TABLE tickers
    ADD COLUMN IF NOT EXISTS industry TEXT;

ALTER TABLE metrics
    ADD COLUMN IF NOT EXISTS currency TEXT;

ALTER TABLE metrics
    DROP COLUMN IF EXISTS sector;

ALTER TABLE metrics
    DROP COLUMN IF EXISTS industry;
