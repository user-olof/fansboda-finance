-- Step 16: company description from yfinance longBusinessSummary on *_tickers (PRD §6).
-- Idempotent. Populate existing rows with:
--   pipenv run python seed_tickers.py --update-business-summary [--country us|swe|uk]

ALTER TABLE us_tickers ADD COLUMN IF NOT EXISTS business_summary TEXT;
ALTER TABLE swe_tickers ADD COLUMN IF NOT EXISTS business_summary TEXT;
ALTER TABLE uk_tickers ADD COLUMN IF NOT EXISTS business_summary TEXT;
