-- Add current_price column to metrics. Run once in the Neon SQL editor
-- before deploying the updated fetch_sma.py.

ALTER TABLE metrics
ADD COLUMN IF NOT EXISTS current_price NUMERIC(18, 6);
