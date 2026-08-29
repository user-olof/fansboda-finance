"""Database access for the metrics table."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
from psycopg2.extras import execute_values

from models import MetricRow

INSERT_METRICS_SQL = """
INSERT INTO metrics (
    ticker, company, trading_date, updated_at,
    currency, sma_50, sma_200, current_price, raw_50, raw_200
)
VALUES %s
ON CONFLICT (ticker, trading_date) DO NOTHING
"""

FRESH_TICKERS_SQL = """
SELECT lt.ticker
FROM (
    SELECT ticker, MAX(trading_date) AS latest_trading_date
    FROM metrics
    WHERE ticker = ANY(%s)
    GROUP BY ticker
) lt
WHERE lt.latest_trading_date = (SELECT MAX(trading_date) FROM metrics)
"""

EXISTING_METRICS_SQL = """
SELECT ticker, trading_date
FROM metrics
WHERE ticker = ANY(%s)
"""

DELETE_STALE_SQL = """
DELETE FROM metrics
WHERE trading_date < %s
"""


def retention_cutoff(retention_days: int, *, today: date | None = None) -> date:
    """Return the oldest trading_date to keep (exclusive delete boundary)."""
    anchor = today if today is not None else datetime.now(timezone.utc).date()
    return anchor - timedelta(days=retention_days)


def _metric_values(rows: list[MetricRow], *, updated_at: datetime) -> list[tuple]:
    return [
        (
            row.ticker,
            row.company,
            row.trading_date,
            updated_at,
            row.currency,
            row.sma_50,
            row.sma_200,
            row.current_price,
            row.raw_50,
            row.raw_200,
        )
        for row in rows
    ]


def insert_metrics(database_url: str, rows: list[MetricRow]) -> int:
    """Append metric rows, skipping duplicates. Returns rows inserted."""
    if not rows:
        return 0

    now = datetime.now(timezone.utc)
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            execute_values(
                cur, INSERT_METRICS_SQL, _metric_values(rows, updated_at=now)
            )
            inserted = cur.rowcount
        conn.commit()

    return inserted


def load_existing_metric_keys(
    database_url: str, tickers: list[str]
) -> set[tuple[str, date]]:
    """Return (ticker, trading_date) pairs already stored for the given tickers."""
    if not tickers:
        return set()

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(EXISTING_METRICS_SQL, (tickers,))
            return {(row[0], row[1]) for row in cur.fetchall()}


def filter_stale_tickers(
    database_url: str, tickers: list[str]
) -> tuple[list[str], int, date | None]:
    """Return tickers needing fetch (PRD FR-2).

    A ticker is fresh when its latest ``trading_date`` equals the global max
    ``trading_date`` in ``metrics`` — i.e. it already has a row for the current
    market session. All others are stale and need fetching.
    """
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(trading_date) FROM metrics")
            max_row = cur.fetchone()

            if not max_row or max_row[0] is None:
                return tickers, 0, None

            max_date = max_row[0]
            cur.execute(FRESH_TICKERS_SQL, (tickers,))
            fresh = {row[0] for row in cur.fetchall()}

    stale = [ticker for ticker in tickers if ticker not in fresh]
    skipped = len(tickers) - len(stale)
    return stale, skipped, max_date


LOAD_RAW_RATIOS_BY_MARKET_FOR_DATE_SQL = """
SELECT t.market, m.raw_50, m.raw_200
FROM metrics m
JOIN tickers t ON t.symbol = m.ticker
WHERE m.trading_date = %s
"""

LOAD_DISTINCT_TRADING_DATES_SQL = """
SELECT DISTINCT trading_date
FROM metrics
ORDER BY trading_date
"""


def load_raw_ratios_by_market_for_date(
    database_url: str,
    trading_date: date,
) -> dict[str | None, tuple[list[Decimal], list[Decimal]]]:
    """Return raw_50/raw_200 values grouped by tickers.market for a trading_date."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(LOAD_RAW_RATIOS_BY_MARKET_FOR_DATE_SQL, (trading_date,))
            rows = cur.fetchall()

    grouped: dict[str | None, tuple[list[Decimal], list[Decimal]]] = {}
    for market, raw_50, raw_200 in rows:
        raw_50_values, raw_200_values = grouped.setdefault(market, ([], []))
        if raw_50 is not None:
            raw_50_values.append(raw_50)
        if raw_200 is not None:
            raw_200_values.append(raw_200)

    return grouped


def load_distinct_trading_dates(database_url: str) -> list[date]:
    """Return all distinct trading_date values in metrics, oldest first."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(LOAD_DISTINCT_TRADING_DATES_SQL)
            return [row[0] for row in cur.fetchall()]


def purge_stale_metrics(database_url: str, retention_days: int) -> int:
    """Delete metrics rows older than retention_days (UTC). Returns rows deleted."""
    cutoff = retention_cutoff(retention_days)
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DELETE_STALE_SQL, (cutoff,))
            deleted = cur.rowcount
        conn.commit()

    return deleted
