-- Step 24: market index z_score 0 (specs/005-market-index-zero-z).
-- Market rows (US-IDX / SWE-IDX / UK-IDX) get z_score 0 instead of NULL: the
-- market is the reference its sectors are compared with.
-- Data only: no other column and no sector row (US-IDX-TECHNOLOGY, …) changes.
-- Safe to repeat. Apply after step 23 and after deploying the 005 code; if an
-- older deployment wrote a market row in between, apply it again.

UPDATE indices
SET z_score = 0
WHERE ticker IN ('US-IDX', 'SWE-IDX', 'UK-IDX')
  AND z_score IS DISTINCT FROM 0;
