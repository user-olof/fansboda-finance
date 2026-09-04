"""Database access for the country metrics tables (RFC-001)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
from psycopg2.extras import execute_values

from db.country import CountrySet, country_set_for
from models import MetricRow

INSERT_METRICS_SQL = {
    CountrySet.US: """
INSERT INTO us_metrics (
    ticker, company, trading_date, updated_at,
    currency, sma_50, sma_200, current_price, raw_50, raw_200
)
VALUES %s
ON CONFLICT (ticker, trading_date) DO NOTHING
""",
    CountrySet.SWE: """
INSERT INTO swe_metrics (
    ticker, company, trading_date, updated_at,
    currency, sma_50, sma_200, current_price, raw_50, raw_200
)
VALUES %s
ON CONFLICT (ticker, trading_date) DO NOTHING
""",
}

MAX_TRADING_DATE_SQL = {
    CountrySet.US: "SELECT MAX(trading_date) FROM us_metrics",
    CountrySet.SWE: "SELECT MAX(trading_date) FROM swe_metrics",
}

FRESH_TICKERS_SQL = {
    CountrySet.US: """
SELECT lt.ticker
FROM (
    SELECT ticker, MAX(trading_date) AS latest_trading_date
    FROM us_metrics
    WHERE ticker = ANY(%s)
    GROUP BY ticker
) lt
WHERE lt.latest_trading_date = (SELECT MAX(trading_date) FROM us_metrics)
""",
    CountrySet.SWE: """
SELECT lt.ticker
FROM (
    SELECT ticker, MAX(trading_date) AS latest_trading_date
    FROM swe_metrics
    WHERE ticker = ANY(%s)
    GROUP BY ticker
) lt
WHERE lt.latest_trading_date = (SELECT MAX(trading_date) FROM swe_metrics)
""",
}

EXISTING_METRICS_SQL = """
SELECT ticker, trading_date FROM us_metrics WHERE ticker = ANY(%s)
UNION ALL
SELECT ticker, trading_date FROM swe_metrics WHERE ticker = ANY(%s)
"""

DELETE_STALE_SQL = (
    "DELETE FROM us_metrics WHERE trading_date < %s",
    "DELETE FROM swe_metrics WHERE trading_date < %s",
)

LOAD_RAW_RATIOS_BY_MARKET_FOR_DATE_SQL = """
SELECT t.market, m.raw_50, m.raw_200
FROM us_metrics m
JOIN us_tickers t ON t.symbol = m.ticker
WHERE m.trading_date = %s
UNION ALL
SELECT t.market, m.raw_50, m.raw_200
FROM swe_metrics m
JOIN swe_tickers t ON t.symbol = m.ticker
WHERE m.trading_date = %s
"""

LOAD_DISTINCT_TRADING_DATES_SQL = """
SELECT DISTINCT trading_date FROM (
    SELECT trading_date FROM us_metrics
    UNION ALL
    SELECT trading_date FROM swe_metrics
) dates
ORDER BY trading_date
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
    """Append metric rows into us_metrics / swe_metrics. Returns rows inserted."""
    if not rows:
        return 0

    by_country: dict[CountrySet, list[MetricRow]] = defaultdict(list)
    for row in rows:
        by_country[country_set_for(symbol=row.ticker)].append(row)

    now = datetime.now(timezone.utc)
    inserted = 0
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for country, country_rows in by_country.items():
                execute_values(
                    cur,
                    INSERT_METRICS_SQL[country],
                    _metric_values(country_rows, updated_at=now),
                )
                inserted += cur.rowcount
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
            cur.execute(EXISTING_METRICS_SQL, (tickers, tickers))
            return {(row[0], row[1]) for row in cur.fetchall()}


def filter_stale_tickers(
    database_url: str, tickers: list[str]
) -> tuple[list[str], int, date | None]:
    """Return tickers needing fetch (PRD FR-2 / RFC-003).

    Freshness is evaluated **per country set**: a ticker is fresh when its latest
    ``trading_date`` in ``us_metrics`` or ``swe_metrics`` equals that table's
    ``MAX(trading_date)``. US and Swedish calendars are compared separately.
    """
    by_country: dict[CountrySet, list[str]] = defaultdict(list)
    for ticker in tickers:
        by_country[country_set_for(symbol=ticker)].append(ticker)

    fresh: set[str] = set()
    max_dates: list[date] = []

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for country, country_tickers in by_country.items():
                cur.execute(MAX_TRADING_DATE_SQL[country])
                max_row = cur.fetchone()
                if not max_row or max_row[0] is None:
                    continue

                max_dates.append(max_row[0])
                cur.execute(FRESH_TICKERS_SQL[country], (country_tickers,))
                fresh.update(row[0] for row in cur.fetchall())

    stale = [ticker for ticker in tickers if ticker not in fresh]
    skipped = len(tickers) - len(stale)
    max_date = max(max_dates) if max_dates else None
    return stale, skipped, max_date


def load_raw_ratios_by_market_for_date(
    database_url: str,
    trading_date: date,
) -> dict[str | None, tuple[list[Decimal], list[Decimal]]]:
    """Return raw_50/raw_200 values grouped by tickers.market for a trading_date."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                LOAD_RAW_RATIOS_BY_MARKET_FOR_DATE_SQL,
                (trading_date, trading_date),
            )
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
    """Return all distinct trading_date values across country metrics tables."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(LOAD_DISTINCT_TRADING_DATES_SQL)
            return [row[0] for row in cur.fetchall()]


def purge_stale_metrics(database_url: str, retention_days: int) -> int:
    """Delete stale rows from ``us_metrics`` and ``swe_metrics`` (RFC-004)."""
    cutoff = retention_cutoff(retention_days)
    deleted = 0
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for sql in DELETE_STALE_SQL:
                cur.execute(sql, (cutoff,))
                deleted += cur.rowcount
        conn.commit()

    return deleted
