"""Database access for the country ``*_by_sector`` trend tables (PRD §5.7)."""

from __future__ import annotations

from datetime import date

import psycopg2

from db.country import CountrySet, sql_for_countries

# Sector labels are normalized to the yfinance ``sectorKey`` form so a display
# name fallback ("Consumer Cyclical") and a key ("consumer-cyclical") merge.
SECTOR_KEY_SQL = "lower(replace(btrim(t.sector), ' ', '-'))"

DELETE_SECTOR_WEEK_SQL = sql_for_countries(
    "DELETE FROM {by_sector} WHERE week_start = %s"
)

INSERT_SECTOR_WEEK_SQL = sql_for_countries(
    f"""
INSERT INTO {{by_sector}} (
    sector, week_start, updated_at, ticker_count,
    momentum_mean, momentum_median, z_score_mean, pct_uptrend
)
SELECT
    {SECTOR_KEY_SQL} AS sector,
    m.week_start,
    NOW(),
    COUNT(*),
    AVG(m.momentum),
    percentile_cont(0.5) WITHIN GROUP (ORDER BY m.momentum),
    AVG(m.z_score),
    100.0 * AVG(CASE WHEN m.sma_50 > m.sma_200 THEN 1 ELSE 0 END)
FROM {{metrics}} m
JOIN {{tickers}} t ON t.symbol = m.ticker
WHERE m.week_start = %s
  AND m.momentum IS NOT NULL
  AND t.sector IS NOT NULL
  AND btrim(t.sector) <> ''
GROUP BY {SECTOR_KEY_SQL}, m.week_start
"""
)

PRUNE_ORPHAN_SECTOR_WEEKS_SQL = sql_for_countries(
    """
DELETE FROM {by_sector} s
WHERE NOT EXISTS (
    SELECT 1 FROM {metrics} m WHERE m.week_start = s.week_start
)
"""
)


def refresh_sector_weeks(
    database_url: str,
    week_starts: list[date],
    *,
    country: CountrySet,
) -> int:
    """Recompute ``*_by_sector`` rows for each week from the metrics table.

    Each week is replaced atomically (delete + insert in one transaction), so
    sectors that no longer have tickers disappear. Returns rows written.
    """
    written = 0
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for week_start in week_starts:
                cur.execute(DELETE_SECTOR_WEEK_SQL[country], (week_start,))
                cur.execute(INSERT_SECTOR_WEEK_SQL[country], (week_start,))
                written += cur.rowcount
        conn.commit()

    return written


def prune_orphan_sector_weeks(database_url: str, *, country: CountrySet) -> int:
    """Delete ``*_by_sector`` weeks with no remaining metrics rows (retention)."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(PRUNE_ORPHAN_SECTOR_WEEKS_SQL[country])
            deleted = cur.rowcount
        conn.commit()

    return deleted
