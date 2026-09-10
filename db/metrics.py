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
    currency, sma_50, sma_200, current_price, momentum, z_score
)
VALUES %s
ON CONFLICT (ticker, trading_date) DO NOTHING
""",
    CountrySet.SWE: """
INSERT INTO swe_metrics (
    ticker, company, trading_date, updated_at,
    currency, sma_50, sma_200, current_price, momentum, z_score
)
VALUES %s
ON CONFLICT (ticker, trading_date) DO NOTHING
""",
    CountrySet.UK: """
INSERT INTO uk_metrics (
    ticker, company, trading_date, updated_at,
    currency, sma_50, sma_200, current_price, momentum, z_score
)
VALUES %s
ON CONFLICT (ticker, trading_date) DO NOTHING
""",
}

MAX_TRADING_DATE_SQL = {
    CountrySet.US: "SELECT MAX(trading_date) FROM us_metrics",
    CountrySet.SWE: "SELECT MAX(trading_date) FROM swe_metrics",
    CountrySet.UK: "SELECT MAX(trading_date) FROM uk_metrics",
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
    CountrySet.UK: """
SELECT lt.ticker
FROM (
    SELECT ticker, MAX(trading_date) AS latest_trading_date
    FROM uk_metrics
    WHERE ticker = ANY(%s)
    GROUP BY ticker
) lt
WHERE lt.latest_trading_date = (SELECT MAX(trading_date) FROM uk_metrics)
""",
}

EXISTING_METRICS_SQL = """
SELECT ticker, trading_date FROM us_metrics WHERE ticker = ANY(%s)
UNION ALL
SELECT ticker, trading_date FROM swe_metrics WHERE ticker = ANY(%s)
UNION ALL
SELECT ticker, trading_date FROM uk_metrics WHERE ticker = ANY(%s)
"""

DELETE_STALE_SQL = (
    "DELETE FROM us_metrics WHERE trading_date < %s",
    "DELETE FROM swe_metrics WHERE trading_date < %s",
    "DELETE FROM uk_metrics WHERE trading_date < %s",
)

LOAD_MOMENTUM_BY_MARKET_FOR_DATE_SQL = """
SELECT t.market, m.momentum
FROM us_metrics m
JOIN us_tickers t ON t.symbol = m.ticker
WHERE m.trading_date = %s
UNION ALL
SELECT t.market, m.momentum
FROM swe_metrics m
JOIN swe_tickers t ON t.symbol = m.ticker
WHERE m.trading_date = %s
UNION ALL
SELECT t.market, m.momentum
FROM uk_metrics m
JOIN uk_tickers t ON t.symbol = m.ticker
WHERE m.trading_date = %s
"""

UPDATE_Z_SCORES_SQL = {
    CountrySet.US: """
UPDATE us_metrics m
SET z_score = CASE
    WHEN m.momentum IS NULL
         OR mm.momentum_mean IS NULL
         OR mm.momentum_std IS NULL
         OR mm.momentum_std = 0
    THEN NULL
    ELSE (m.momentum - mm.momentum_mean) / mm.momentum_std
END
FROM us_tickers t
JOIN us_market_metrics mm
  ON mm.market = t.market
WHERE m.ticker = t.symbol
  AND mm.trading_date = m.trading_date
  AND m.trading_date = %s
""",
    CountrySet.SWE: """
UPDATE swe_metrics m
SET z_score = CASE
    WHEN m.momentum IS NULL
         OR mm.momentum_mean IS NULL
         OR mm.momentum_std IS NULL
         OR mm.momentum_std = 0
    THEN NULL
    ELSE (m.momentum - mm.momentum_mean) / mm.momentum_std
END
FROM swe_tickers t
JOIN swe_market_metrics mm
  ON mm.market = t.market
WHERE m.ticker = t.symbol
  AND mm.trading_date = m.trading_date
  AND m.trading_date = %s
""",
    CountrySet.UK: """
UPDATE uk_metrics m
SET z_score = CASE
    WHEN m.momentum IS NULL
         OR mm.momentum_mean IS NULL
         OR mm.momentum_std IS NULL
         OR mm.momentum_std = 0
    THEN NULL
    ELSE (m.momentum - mm.momentum_mean) / mm.momentum_std
END
FROM uk_tickers t
JOIN uk_market_metrics mm
  ON mm.market = t.market
WHERE m.ticker = t.symbol
  AND mm.trading_date = m.trading_date
  AND m.trading_date = %s
""",
}

LOAD_DISTINCT_TRADING_DATES_SQL = {
    CountrySet.US: """
SELECT DISTINCT trading_date FROM us_metrics ORDER BY trading_date
""",
    CountrySet.SWE: """
SELECT DISTINCT trading_date FROM swe_metrics ORDER BY trading_date
""",
    CountrySet.UK: """
SELECT DISTINCT trading_date FROM uk_metrics ORDER BY trading_date
""",
}

LOAD_ALL_DISTINCT_TRADING_DATES_SQL = """
SELECT DISTINCT trading_date FROM (
    SELECT trading_date FROM us_metrics
    UNION ALL
    SELECT trading_date FROM swe_metrics
    UNION ALL
    SELECT trading_date FROM uk_metrics
) dates
ORDER BY trading_date
"""

RECOMPUTE_MOMENTUM_SQL = {
    CountrySet.US: """
UPDATE us_metrics
SET momentum = CASE
    WHEN sma_50 IS NULL OR sma_200 IS NULL OR sma_200 = 0 THEN NULL
    ELSE sma_50 / sma_200
END
""",
    CountrySet.SWE: """
UPDATE swe_metrics
SET momentum = CASE
    WHEN sma_50 IS NULL OR sma_200 IS NULL OR sma_200 = 0 THEN NULL
    ELSE sma_50 / sma_200
END
""",
    CountrySet.UK: """
UPDATE uk_metrics
SET momentum = CASE
    WHEN sma_50 IS NULL OR sma_200 IS NULL OR sma_200 = 0 THEN NULL
    ELSE sma_50 / sma_200
END
""",
}


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
            row.momentum,
            row.z_score,
        )
        for row in rows
    ]


def insert_metrics(database_url: str, rows: list[MetricRow]) -> int:
    """Append metric rows into country metrics tables. Returns rows inserted."""
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
            cur.execute(EXISTING_METRICS_SQL, (tickers, tickers, tickers))
            return {(row[0], row[1]) for row in cur.fetchall()}


def filter_stale_tickers(
    database_url: str, tickers: list[str]
) -> tuple[list[str], int, date | None]:
    """Return tickers needing fetch (PRD FR-2 / RFC-003).

    Freshness is evaluated **per country set**: a ticker is fresh when its latest
    ``trading_date`` in the matching ``*_metrics`` table equals that table's
    ``MAX(trading_date)``. US, Swedish, and UK calendars are compared separately.
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


def load_momentum_by_market_for_date(
    database_url: str,
    trading_date: date,
) -> dict[str | None, list[Decimal]]:
    """Return momentum values grouped by tickers.market for a trading_date."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                LOAD_MOMENTUM_BY_MARKET_FOR_DATE_SQL,
                (trading_date, trading_date, trading_date),
            )
            rows = cur.fetchall()

    grouped: dict[str | None, list[Decimal]] = {}
    for market, momentum in rows:
        values = grouped.setdefault(market, [])
        if momentum is not None:
            values.append(momentum)

    return grouped


def update_z_scores_for_trading_date(
    database_url: str,
    trading_date: date,
    *,
    country: CountrySet | None = None,
) -> int:
    """Set z_score from market aggregates for all metrics on ``trading_date``."""
    countries = [country] if country is not None else list(CountrySet)
    updated = 0
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for set_key in countries:
                cur.execute(UPDATE_Z_SCORES_SQL[set_key], (trading_date,))
                updated += cur.rowcount
        conn.commit()

    return updated


def load_distinct_trading_dates(
    database_url: str,
    *,
    country: CountrySet | None = None,
) -> list[date]:
    """Return distinct trading_date values from country metrics tables."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            if country is None:
                cur.execute(LOAD_ALL_DISTINCT_TRADING_DATES_SQL)
            else:
                cur.execute(LOAD_DISTINCT_TRADING_DATES_SQL[country])
            return [row[0] for row in cur.fetchall()]


def recompute_momentum_from_smas(
    database_url: str,
    *,
    country: CountrySet | None = None,
) -> int:
    """Set ``momentum = sma_50 / sma_200`` on metrics rows (DB-only recompute)."""
    countries = [country] if country is not None else list(CountrySet)
    updated = 0
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for set_key in countries:
                cur.execute(RECOMPUTE_MOMENTUM_SQL[set_key])
                updated += cur.rowcount
        conn.commit()

    return updated


def purge_stale_metrics(database_url: str, retention_days: int) -> int:
    """Delete stale rows from country ``*_metrics`` tables (RFC-004)."""
    cutoff = retention_cutoff(retention_days)
    deleted = 0
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for sql in DELETE_STALE_SQL:
                cur.execute(sql, (cutoff,))
                deleted += cur.rowcount
        conn.commit()

    return deleted
