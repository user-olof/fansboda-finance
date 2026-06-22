-- Add updated_at to tickers (RFC-001, PRD §6).
-- Safe to re-run.

ALTER TABLE tickers
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
