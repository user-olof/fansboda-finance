-- Step 14: replace raw_* SMA/price ratios with momentum / z_score (PRD §6 / RFC-012).
-- Idempotent where possible: ADD IF NOT EXISTS then DROP old columns.

-- Metrics: add new columns
ALTER TABLE us_metrics ADD COLUMN IF NOT EXISTS momentum NUMERIC(18, 6);
ALTER TABLE us_metrics ADD COLUMN IF NOT EXISTS z_score NUMERIC(18, 6);
ALTER TABLE swe_metrics ADD COLUMN IF NOT EXISTS momentum NUMERIC(18, 6);
ALTER TABLE swe_metrics ADD COLUMN IF NOT EXISTS z_score NUMERIC(18, 6);
ALTER TABLE uk_metrics ADD COLUMN IF NOT EXISTS momentum NUMERIC(18, 6);
ALTER TABLE uk_metrics ADD COLUMN IF NOT EXISTS z_score NUMERIC(18, 6);

-- Market metrics: add new columns
ALTER TABLE us_market_metrics ADD COLUMN IF NOT EXISTS momentum_mean NUMERIC(18, 6);
ALTER TABLE us_market_metrics ADD COLUMN IF NOT EXISTS momentum_std NUMERIC(18, 6);
ALTER TABLE swe_market_metrics ADD COLUMN IF NOT EXISTS momentum_mean NUMERIC(18, 6);
ALTER TABLE swe_market_metrics ADD COLUMN IF NOT EXISTS momentum_std NUMERIC(18, 6);
ALTER TABLE uk_market_metrics ADD COLUMN IF NOT EXISTS momentum_mean NUMERIC(18, 6);
ALTER TABLE uk_market_metrics ADD COLUMN IF NOT EXISTS momentum_std NUMERIC(18, 6);

-- Drop superseded raw_* columns
ALTER TABLE us_metrics DROP COLUMN IF EXISTS raw_50;
ALTER TABLE us_metrics DROP COLUMN IF EXISTS raw_200;
ALTER TABLE swe_metrics DROP COLUMN IF EXISTS raw_50;
ALTER TABLE swe_metrics DROP COLUMN IF EXISTS raw_200;
ALTER TABLE uk_metrics DROP COLUMN IF EXISTS raw_50;
ALTER TABLE uk_metrics DROP COLUMN IF EXISTS raw_200;

ALTER TABLE us_market_metrics DROP COLUMN IF EXISTS raw_mean_50;
ALTER TABLE us_market_metrics DROP COLUMN IF EXISTS raw_mean_200;
ALTER TABLE us_market_metrics DROP COLUMN IF EXISTS raw_std_50;
ALTER TABLE us_market_metrics DROP COLUMN IF EXISTS raw_std_200;
ALTER TABLE swe_market_metrics DROP COLUMN IF EXISTS raw_mean_50;
ALTER TABLE swe_market_metrics DROP COLUMN IF EXISTS raw_mean_200;
ALTER TABLE swe_market_metrics DROP COLUMN IF EXISTS raw_std_50;
ALTER TABLE swe_market_metrics DROP COLUMN IF EXISTS raw_std_200;
ALTER TABLE uk_market_metrics DROP COLUMN IF EXISTS raw_mean_50;
ALTER TABLE uk_market_metrics DROP COLUMN IF EXISTS raw_mean_200;
ALTER TABLE uk_market_metrics DROP COLUMN IF EXISTS raw_std_50;
ALTER TABLE uk_market_metrics DROP COLUMN IF EXISTS raw_std_200;
