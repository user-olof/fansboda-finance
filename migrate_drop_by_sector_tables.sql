-- Step 22: drop the sector trend tables superseded by the sector index rows in
-- indices (PRD §5.7, RFC-018). Destructive: run only after step 21, the
-- RFC-018 deploy, a compute_indices.py rebuild, and once no consumer (e.g.
-- fansboda) reads *_by_sector. Take a Neon branch snapshot first. Safe to repeat.

DROP TABLE IF EXISTS us_by_sector;
DROP TABLE IF EXISTS swe_by_sector;
DROP TABLE IF EXISTS uk_by_sector;
