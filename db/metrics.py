"""Database access for the metrics table."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import execute_values

from models import MetricRow

INSERT_METRICS_SQL = """
INSERT INTO metrics (
    ticker, name, trading_date, updated_at,
    currency, sma_50, sma_200, current_price
)
VALUES %s
ON CONFLICT (ticker, trading_date) DO NOTHING
"""

FRESH_TICKERS_SQL = """
SELECT ticker
FROM metrics
WHERE ticker = ANY(%s)
  AND trading_date = (SELECT MAX(trading_date) FROM metrics)
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
            row.name,
            row.trading_date,
            updated_at,
            row.currency,
            row.sma_50,
            row.sma_200,
            row.current_price,
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
    """Return tickers needing fetch; skip those already at global max trading_date."""
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


def purge_stale_metrics(database_url: str, retention_days: int) -> int:
    """Delete metrics rows older than retention_days (UTC). Returns rows deleted."""
    cutoff = retention_cutoff(retention_days)
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DELETE_STALE_SQL, (cutoff,))
            deleted = cur.rowcount
        conn.commit()

    return deleted
