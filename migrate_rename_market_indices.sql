-- Step 23: market index labels after the exchanges they cover (specs/003-market-index-names).
-- Relabels stored market rows (indices.sector on US-IDX / SWE-IDX / UK-IDX):
--   US Equity Index → NYSE & Nasdaq, OMX Equity Index → OMX Stockholm,
--   FTSE Equity Index → FTSE London.
-- Data only: no other column and no sector row (US-IDX-TECHNOLOGY, …) changes.
-- Safe to repeat. Apply after deploying the 003 code; if an older deployment
-- wrote a market row in between, apply it again.

UPDATE indices AS i
SET sector = v.label
FROM (
    VALUES
        ('US-IDX', 'NYSE & Nasdaq'),
        ('SWE-IDX', 'OMX Stockholm'),
        ('UK-IDX', 'FTSE London')
) AS v (ticker, label)
WHERE i.ticker = v.ticker
  AND i.sector IS DISTINCT FROM v.label;
