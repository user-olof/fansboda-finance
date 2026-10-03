"""Database access for the shared ``indices`` table (PRD §5.8 / RFC-015)."""

from __future__ import annotations

from datetime import date, timedelta

import psycopg2

from db.country import CountrySet, sql_for_countries
from db.metrics import retention_cutoff
from equity_index import (
    INDEX_DEFINITIONS,
    IndexLevels,
    IndexRow,
    build_base_row,
    build_chained_row,
)
from models import week_start_of

LOAD_PREVIOUS_INDEX_SQL = """
SELECT trading_date, current_price, sma_50, sma_200
FROM indices
WHERE ticker = %s AND trading_date < %s
ORDER BY trading_date DESC
LIMIT 1
"""

BASE_WEEK_STATS_SQL = sql_for_countries(
    """
SELECT
    COUNT(*),
    MAX(trading_date),
    AVG(sma_50 / current_price),
    AVG(sma_200 / current_price)
FROM {metrics}
WHERE week_start = %s
  AND current_price > 0 AND sma_50 > 0 AND sma_200 > 0
"""
)

# Equal-weighted mean growth per measure over stocks with positive price and
# SMAs in both the previous index week and this week (one set for all levels).
CHAINED_WEEK_STATS_SQL = sql_for_countries(
    """
SELECT
    COUNT(*),
    MAX(cur.trading_date),
    AVG(cur.current_price / prev.current_price - 1),
    AVG(cur.sma_50 / prev.sma_50 - 1),
    AVG(cur.sma_200 / prev.sma_200 - 1)
FROM {metrics} cur
JOIN {metrics} prev
  ON prev.ticker = cur.ticker
 AND prev.week_start = %s
WHERE cur.week_start = %s
  AND cur.current_price > 0 AND cur.sma_50 > 0 AND cur.sma_200 > 0
  AND prev.current_price > 0 AND prev.sma_50 > 0 AND prev.sma_200 > 0
"""
)

INSERT_INDEX_SQL = """
INSERT INTO indices (
    ticker, name, country, trading_date, updated_at,
    ticker_count, current_price, sma_50, sma_200, momentum
)
VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s)
"""

DELETE_INDEX_WEEK_SQL = """
DELETE FROM indices
WHERE ticker = %s AND trading_date >= %s AND trading_date < %s
"""

DELETE_INDEX_SQL = "DELETE FROM indices WHERE ticker = %s"

DELETE_STALE_INDICES_SQL = "DELETE FROM indices WHERE trading_date < %s"


def write_index_weeks(
    database_url: str,
    week_starts: list[date],
    *,
    country: CountrySet,
    rebuild: bool = False,
) -> list[IndexRow]:
    """Compute and store the country's index for each week, in ascending order.

    Each week chains from the latest stored row before it, so later weeks see
    the rows written earlier in the same call. The week's existing row (any
    ``trading_date`` in that calendar week) is replaced. ``rebuild=True`` first
    deletes every row for the index, making the earliest week the base week.
    A week with no contributing stocks ends up with no row (FR-41). One
    transaction.
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
                    cur.execute(BASE_WEEK_STATS_SQL[country], (week_start,))
                    ticker_count, trading_date, sma_50_ratio, sma_200_ratio = (
                        cur.fetchone()
                    )
                    row = build_base_row(
                        definition,
                        trading_date=trading_date,
                        ticker_count=ticker_count,
                        avg_sma_50_ratio=sma_50_ratio,
                        avg_sma_200_ratio=sma_200_ratio,
                    )
                else:
                    prev_date, prev_price, prev_sma_50, prev_sma_200 = previous
                    cur.execute(
                        CHAINED_WEEK_STATS_SQL[country],
                        (week_start_of(prev_date), week_start),
                    )
                    (
                        ticker_count,
                        trading_date,
                        growth_price,
                        growth_sma_50,
                        growth_sma_200,
                    ) = cur.fetchone()
                    row = build_chained_row(
                        definition,
                        IndexLevels(prev_price, prev_sma_50, prev_sma_200),
                        trading_date=trading_date,
                        ticker_count=ticker_count,
                        growth_price=growth_price,
                        growth_sma_50=growth_sma_50,
                        growth_sma_200=growth_sma_200,
                    )

                cur.execute(
                    DELETE_INDEX_WEEK_SQL,
                    (definition.ticker, week_start, week_start + timedelta(days=7)),
                )
                if row is None:
                    continue
                cur.execute(
                    INSERT_INDEX_SQL,
                    (
                        row.ticker,
                        row.name,
                        row.country.value,
                        row.trading_date,
                        row.ticker_count,
                        row.current_price,
                        row.sma_50,
                        row.sma_200,
                        row.momentum,
                    ),
                )
                written.append(row)
        conn.commit()

    return written


def purge_stale_indices(database_url: str, retention_days: int) -> int:
    """Delete ``indices`` rows with ``trading_date`` before the retention cutoff."""
    cutoff = retention_cutoff(retention_days)
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DELETE_STALE_INDICES_SQL, (cutoff,))
            deleted = cur.rowcount
        conn.commit()

    return deleted
