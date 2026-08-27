-- Index for retention purge (RFC-001, RFC-004).
-- Safe to re-run.

CREATE INDEX IF NOT EXISTS idx_metrics_trading_date ON metrics (trading_date);
