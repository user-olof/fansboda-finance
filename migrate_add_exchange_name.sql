-- Step 12: add exchange_name to country tickers tables (PRD §6 / RFC-001).
-- Idempotent. uk_tickers may not exist yet (created in step 13).

ALTER TABLE us_tickers
    ADD COLUMN IF NOT EXISTS exchange_name TEXT;

ALTER TABLE swe_tickers
    ADD COLUMN IF NOT EXISTS exchange_name TEXT;

DO $$
BEGIN
    IF to_regclass('public.uk_tickers') IS NOT NULL THEN
        ALTER TABLE uk_tickers
            ADD COLUMN IF NOT EXISTS exchange_name TEXT;
    END IF;
END $$;
