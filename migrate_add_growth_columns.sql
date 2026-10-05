-- Step 20: weekly growth columns on the country metrics tables (PRD FR-5a /
-- §6, RFC-016). Growth vs the previous calendar week's last bar, computed
-- from one adjusted yfinance download. Additive and safe to repeat.
-- Fill history afterwards per country set:
--   pipenv run python backfill_sma.py --country us   (then swe, uk)
-- then rebuild indices:
--   pipenv run python compute_indices.py

ALTER TABLE us_metrics
    ADD COLUMN IF NOT EXISTS price_growth   NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS sma_50_growth  NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS sma_200_growth NUMERIC(18, 6);

ALTER TABLE swe_metrics
    ADD COLUMN IF NOT EXISTS price_growth   NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS sma_50_growth  NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS sma_200_growth NUMERIC(18, 6);

ALTER TABLE uk_metrics
    ADD COLUMN IF NOT EXISTS price_growth   NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS sma_50_growth  NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS sma_200_growth NUMERIC(18, 6);
