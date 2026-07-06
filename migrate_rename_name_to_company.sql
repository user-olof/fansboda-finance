-- Rename name -> company on tickers and metrics (RFC-001, PRD §6).
-- Safe to re-run.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tickers'
          AND column_name = 'name'
    ) THEN
        ALTER TABLE tickers RENAME COLUMN name TO company;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'metrics'
          AND column_name = 'name'
    ) THEN
        ALTER TABLE metrics RENAME COLUMN name TO company;
    END IF;
END $$;
