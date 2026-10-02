"""Database access for the shared ``indices`` table (PRD §5.8 / RFC-015)."""

from __future__ import annotations

from datetime import date

import psycopg2

from db.country import CountrySet, sql_for_countries
from db.metrics import retention_cutoff
from equity_index import INDEX_DEFINITIONS, IndexRow, build_index_row

LOAD_PREVIOUS_INDEX_SQL = """
SELECT week_start, index_price
FROM indices
WHERE ticker = %s AND week_start < %s
ORDER BY week_start DESC
LIMIT 1
"""

COUNT_PRICED_STOCKS_SQL = sql_for_countries(
    """
SELECT COUNT(*)
FROM {metrics}
WHERE week_start = %s AND current_price > 0
"""
)

# Equal-weighted mean return of stocks priced in both the previous stored
# week and this week.
WEEKLY_RETURN_SQL = sql_for_countries(
    """
SELECT COUNT(*), AVG(cur.current_price / prev.current_price - 1)
FROM {metrics} cur
JOIN {metrics} prev
  ON prev.ticker = cur.ticker
 AND prev.week_start = %s
WHERE cur.week_start = %s
  AND cur.current_price IS NOT NULL
  AND prev.current_price > 0
"""
)

UPSERT_INDEX_SQL = """
INSERT INTO indices (
    ticker, name, country, week_start, updated_at,
    ticker_count, avg_return, index_price
)
VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s)
ON CONFLICT (ticker, week_start) DO UPDATE SET
    name = EXCLUDED.name,
    country = EXCLUDED.country,
    updated_at = EXCLUDED.updated_at,
    ticker_count = EXCLUDED.ticker_count,
    avg_return = EXCLUDED.avg_return,
    index_price = EXCLUDED.index_price
"""

DELETE_INDEX_WEEK_SQL = "DELETE FROM indices WHERE ticker = %s AND week_start = %s"

DELETE_INDEX_SQL = "DELETE FROM indices WHERE ticker = %s"

DELETE_STALE_INDICES_SQL = "DELETE FROM indices WHERE week_start < %s"


def write_index_weeks(
    database_url: str,
    week_starts: list[date],
    *,
    country: CountrySet,
    rebuild: bool = False,
) -> list[IndexRow]:
    """Compute and store the country's index for each week, in ascending order.

    Each week chains from the latest stored row before it, so later weeks see
    the rows written earlier in the same call. ``rebuild=True`` first deletes
    every row for the index, making the earliest week the base week. A week
    with no contributing stocks has its row removed (FR-39). One transaction.
    """
    definition = INDEX_DEFINITIONS[country]
    written: list[IndexRow] = []
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            if rebuild:
                cur.execute(DELETE_INDEX_SQL, (definition.ticker,))
            for week_start in sorted(set(week_starts)):
                cur.execute(LOAD_PREVIOUS_INDEX_SQL, (definition.ticker, week_start))
                previous = cur.fetchone()
                if previous is None:
                    cur.execute(COUNT_PRICED_STOCKS_SQL[country], (week_start,))
                    (ticker_count,) = cur.fetchone()
                    row = build_index_row(
                        definition,
                        week_start,
                        prev_price=None,
                        ticker_count=ticker_count,
                        avg_return=None,
                    )
                else:
                    prev_week, prev_price = previous
                    cur.execute(WEEKLY_RETURN_SQL[country], (prev_week, week_start))
                    ticker_count, avg_return = cur.fetchone()
                    row = build_index_row(
                        definition,
                        week_start,
                        prev_price=prev_price,
                        ticker_count=ticker_count,
                        avg_return=avg_return,
                    )

                if row is None:
                    cur.execute(DELETE_INDEX_WEEK_SQL, (definition.ticker, week_start))
                    continue
                cur.execute(
                    UPSERT_INDEX_SQL,
                    (
                        row.ticker,
                        row.name,
                        row.country.value,
                        row.week_start,
                        row.ticker_count,
                        row.avg_return,
                        row.index_price,
                    ),
                )
                written.append(row)
        conn.commit()

    return written


def purge_stale_indices(database_url: str, retention_days: int) -> int:
    """Delete ``indices`` rows with ``week_start`` before the retention cutoff."""
    cutoff = retention_cutoff(retention_days)
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DELETE_STALE_INDICES_SQL, (cutoff,))
            deleted = cur.rowcount
        conn.commit()

    return deleted
