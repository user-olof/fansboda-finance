"""Database access for the country metrics tables (RFC-001)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
from psycopg2.extras import execute_values

from db.country import (
    METRICS_TABLE,
    CountrySet,
    country_set_for,
    sql_for_countries,
    union_all_sql,
)
from models import MetricRow, week_start_of

INSERT_METRICS_SQL = sql_for_countries(
    """
INSERT INTO {metrics} (
    ticker, company, week_start, trading_date, updated_at,
    currency, sma_50, sma_200, current_price, momentum, z_score,
    price_growth, sma_50_growth, sma_200_growth
)
VALUES %s
ON CONFLICT (ticker, week_start) DO UPDATE SET
    company = EXCLUDED.company,
    trading_date = EXCLUDED.trading_date,
    updated_at = EXCLUDED.updated_at,
    currency = EXCLUDED.currency,
    sma_50 = EXCLUDED.sma_50,
    sma_200 = EXCLUDED.sma_200,
    current_price = EXCLUDED.current_price,
    momentum = EXCLUDED.momentum,
    z_score = EXCLUDED.z_score,
    price_growth = EXCLUDED.price_growth,
    sma_50_growth = EXCLUDED.sma_50_growth,
    sma_200_growth = EXCLUDED.sma_200_growth
WHERE EXCLUDED.trading_date > {metrics}.trading_date
"""
)

# Backfill (FR-16): only rows whose growth columns are all still NULL.
FILL_MISSING_GROWTH_SQL = sql_for_countries(
    """
UPDATE {metrics} m
SET price_growth = v.price_growth::numeric,
    sma_50_growth = v.sma_50_growth::numeric,
    sma_200_growth = v.sma_200_growth::numeric
FROM (VALUES %s) AS v (
    ticker, trading_date, price_growth, sma_50_growth, sma_200_growth
)
WHERE m.ticker = v.ticker
  AND m.trading_date = v.trading_date::date
  AND m.price_growth IS NULL
  AND m.sma_50_growth IS NULL
  AND m.sma_200_growth IS NULL
"""
)

FRESH_TICKERS_SQL = sql_for_countries(
    """
SELECT ticker
FROM {metrics}
WHERE ticker = ANY(%s)
  AND week_start = %s
  AND trading_date >= %s
"""
)

EXISTING_METRICS_SQL = union_all_sql(
    "SELECT ticker, trading_date FROM {metrics} WHERE ticker = ANY(%s)"
)

EXISTING_METRICS_SQL_BY_COUNTRY = sql_for_countries(
    "SELECT ticker, trading_date FROM {metrics} WHERE ticker = ANY(%s)"
)

DELETE_STALE_SQL = tuple(
    f"DELETE FROM {METRICS_TABLE[country]} WHERE trading_date < %s"
    for country in CountrySet
)

LOAD_MOMENTUM_BY_MARKET_FOR_WEEK_SQL = union_all_sql(
    """
SELECT t.market, m.momentum
FROM {metrics} m
JOIN {tickers} t ON t.symbol = m.ticker
WHERE m.week_start = %s
""".strip()
)

UPDATE_Z_SCORES_SQL = sql_for_countries(
    """
UPDATE {metrics} m
SET z_score = CASE
    WHEN m.momentum IS NULL
         OR mm.momentum_mean IS NULL
         OR mm.momentum_std IS NULL
         OR mm.momentum_std = 0
    THEN NULL
    ELSE (m.momentum - mm.momentum_mean) / mm.momentum_std
END
FROM {tickers} t
JOIN {market_metrics} mm
  ON mm.market = t.market
WHERE m.ticker = t.symbol
  AND mm.week_start = m.week_start
  AND m.week_start = %s
"""
)

LOAD_DISTINCT_WEEK_STARTS_SQL = sql_for_countries(
    "SELECT DISTINCT week_start FROM {metrics} ORDER BY week_start"
)

LOAD_ALL_DISTINCT_WEEK_STARTS_SQL = f"""
SELECT DISTINCT week_start FROM (
{union_all_sql("SELECT week_start FROM {metrics}")}
) weeks
ORDER BY week_start
"""

RECOMPUTE_MOMENTUM_SQL = sql_for_countries(
    """
UPDATE {metrics}
SET momentum = CASE
    WHEN sma_50 IS NULL OR sma_200 IS NULL OR sma_200 = 0 THEN NULL
    ELSE sma_50 / sma_200
END
"""
)

def retention_cutoff(retention_days: int, *, today: date | None = None) -> date:
    """Return the oldest trading_date to keep (exclusive delete boundary)."""
    anchor = today if today is not None else datetime.now(timezone.utc).date()
    return anchor - timedelta(days=retention_days)


def _metric_values(rows: list[MetricRow], *, updated_at: datetime) -> list[tuple]:
    return [
        (
            row.ticker,
            row.company,
            row.week_start,
            row.trading_date,
            updated_at,
            row.currency,
            row.sma_50,
            row.sma_200,
            row.current_price,
            row.momentum,
            row.z_score,
            row.price_growth,
            row.sma_50_growth,
            row.sma_200_growth,
        )
        for row in rows
    ]


def insert_metrics(database_url: str, rows: list[MetricRow]) -> int:
    """Upsert one row per (ticker, week_start) into country metrics tables.

    An existing week row is replaced only when the new ``trading_date`` is
    later. Returns rows inserted or updated.
    """
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


def fill_missing_growth(
    database_url: str,
    rows: list[MetricRow],
    *,
    country: CountrySet,
) -> int:
    """Fill growth columns on stored rows where all three are NULL (FR-16).

    Rows are matched on ``(ticker, trading_date)``; nothing else is touched.
    Returns rows updated.
    """
    values = [
        (
            row.ticker,
            row.trading_date,
            row.price_growth,
            row.sma_50_growth,
            row.sma_200_growth,
        )
        for row in rows
        if row.price_growth is not None
        or row.sma_50_growth is not None
        or row.sma_200_growth is not None
    ]
    if not values:
        return 0

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                FILL_MISSING_GROWTH_SQL[country],
                values,
                page_size=len(values),
            )
            updated = cur.rowcount
        conn.commit()

    return updated


def load_existing_metric_keys(
    database_url: str,
    tickers: list[str],
    *,
    country: CountrySet | None = None,
) -> set[tuple[str, date]]:
    """Return (ticker, trading_date) pairs already stored for the given tickers.

    When ``country`` is set, only that set's ``*_metrics`` table is queried.
    """
    if not tickers:
        return set()

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            if country is None:
                cur.execute(EXISTING_METRICS_SQL, (tickers, tickers, tickers))
            else:
                cur.execute(EXISTING_METRICS_SQL_BY_COUNTRY[country], (tickers,))
            return {(row[0], row[1]) for row in cur.fetchall()}


def current_week_start(*, today: date | None = None) -> date:
    """Return Monday of the current UTC week."""
    anchor = today if today is not None else datetime.now(timezone.utc).date()
    return week_start_of(anchor)


def expected_latest_bar(*, today: date | None = None) -> date:
    """Return the newest bar date a fetch run on ``today`` can expect.

    On weekends that is Friday; on weekdays it is ``today``.
    """
    anchor = today if today is not None else datetime.now(timezone.utc).date()
    friday = week_start_of(anchor) + timedelta(days=4)
    return min(anchor, friday)


def filter_stale_tickers(
    database_url: str,
    tickers: list[str],
    *,
    today: date | None = None,
) -> tuple[list[str], int, date]:
    """Return tickers needing fetch (PRD FR-2 / RFC-003).

    A ticker is fresh when its current-week row already holds the newest bar
    the run can expect (``expected_latest_bar``). Returns
    ``(stale, skipped, week_start)``.
    """
    week_start = current_week_start(today=today)
    latest_bar = expected_latest_bar(today=today)
    by_country: dict[CountrySet, list[str]] = defaultdict(list)
    for ticker in tickers:
        by_country[country_set_for(symbol=ticker)].append(ticker)

    fresh: set[str] = set()
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for country, country_tickers in by_country.items():
                cur.execute(
                    FRESH_TICKERS_SQL[country],
                    (country_tickers, week_start, latest_bar),
                )
                fresh.update(row[0] for row in cur.fetchall())

    stale = [ticker for ticker in tickers if ticker not in fresh]
    skipped = len(tickers) - len(stale)
    return stale, skipped, week_start


def load_momentum_by_market_for_week(
    database_url: str,
    week_start: date,
) -> dict[str | None, list[Decimal]]:
    """Return momentum values grouped by tickers.market for one week."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                LOAD_MOMENTUM_BY_MARKET_FOR_WEEK_SQL,
                (week_start, week_start, week_start),
            )
            rows = cur.fetchall()

    grouped: dict[str | None, list[Decimal]] = {}
    for market, momentum in rows:
        values = grouped.setdefault(market, [])
        if momentum is not None:
            values.append(momentum)

    return grouped


def update_z_scores_for_week(
    database_url: str,
    week_start: date,
    *,
    country: CountrySet | None = None,
) -> int:
    """Set z_score from market aggregates for all metrics in ``week_start``."""
    countries = [country] if country is not None else list(CountrySet)
    updated = 0
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for set_key in countries:
                cur.execute(UPDATE_Z_SCORES_SQL[set_key], (week_start,))
                updated += cur.rowcount
        conn.commit()

    return updated


def load_distinct_week_starts(
    database_url: str,
    *,
    country: CountrySet | None = None,
) -> list[date]:
    """Return distinct week_start values from country metrics tables."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            if country is None:
                cur.execute(LOAD_ALL_DISTINCT_WEEK_STARTS_SQL)
            else:
                cur.execute(LOAD_DISTINCT_WEEK_STARTS_SQL[country])
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
