-- Step 21: sector indices in the shared indices table (PRD §5.8 / §6,
-- RFC-018). Adds currency, pct_uptrend, and z_score (sector rows only), and
-- merges name into sector: sector takes over the index label
-- ("US Equity Index" on market rows, "Technology" on sector rows), becomes the second
-- column (after ticker), and name is dropped. Postgres cannot reorder
-- columns, so the table is rebuilt (rows copied) unless sector is already the
-- second column. Safe to repeat.
-- Not additive — code that predates RFC-018 still writes name, so apply this
-- together with the RFC-018 deploy, then rebuild:
--   pipenv run python compute_indices.py
-- and later drop the superseded *_by_sector tables with step 22.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'indices'
          AND column_name = 'sector'
          AND ordinal_position = 2
    ) THEN
        ALTER TABLE indices
            ADD COLUMN IF NOT EXISTS sector      TEXT,
            ADD COLUMN IF NOT EXISTS currency    TEXT,
            ADD COLUMN IF NOT EXISTS pct_uptrend NUMERIC(18, 6),
            ADD COLUMN IF NOT EXISTS z_score     NUMERIC(18, 6);

        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'indices'
              AND column_name = 'name'
        ) THEN
            EXECUTE 'UPDATE indices SET sector = name';
        END IF;

        CREATE TABLE indices_new (
            ticker         TEXT            NOT NULL,
            sector         TEXT            NOT NULL,
            country        TEXT            NOT NULL,
            trading_date   DATE            NOT NULL,
            updated_at     TIMESTAMPTZ     NOT NULL,
            ticker_count   INTEGER         NOT NULL,
            current_price  NUMERIC(18, 6)  NOT NULL,
            sma_50         NUMERIC(18, 6)  NOT NULL,
            sma_200        NUMERIC(18, 6)  NOT NULL,
            momentum       NUMERIC(18, 6),
            currency       TEXT,
            pct_uptrend    NUMERIC(18, 6),
            z_score        NUMERIC(18, 6),
            PRIMARY KEY (ticker, trading_date)
        );

        INSERT INTO indices_new (
            ticker, sector, country, trading_date, updated_at, ticker_count,
            current_price, sma_50, sma_200, momentum, currency, pct_uptrend,
            z_score
        )
        SELECT
            ticker, COALESCE(sector, ticker), country, trading_date, updated_at,
            ticker_count, current_price, sma_50, sma_200, momentum, currency,
            pct_uptrend, z_score
        FROM indices;

        DROP TABLE indices;
        ALTER TABLE indices_new RENAME TO indices;
        ALTER TABLE indices RENAME CONSTRAINT indices_new_pkey TO indices_pkey;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_indices_country_trading_date
    ON indices (country, trading_date);
