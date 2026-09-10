"""Database access for the country market_metrics tables (RFC-001)."""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg2

from db.country import (
    MARKET_METRICS_TABLE,
    CountrySet,
    country_set_for,
    sql_for_countries,
)
from db.metrics import retention_cutoff
from models import MarketRow

UPSERT_MARKET_SQL = sql_for_countries(
    """
INSERT INTO {market_metrics} (
    market, trading_date, updated_at,
    momentum_mean, momentum_std
)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (market, trading_date) DO UPDATE SET
    updated_at = EXCLUDED.updated_at,
    momentum_mean = EXCLUDED.momentum_mean,
    momentum_std = EXCLUDED.momentum_std
"""
)

DELETE_STALE_MARKET_SQL = tuple(
    f"DELETE FROM {MARKET_METRICS_TABLE[country]} WHERE trading_date < %s"
    for country in CountrySet
)


def upsert_market_stats(database_url: str, row: MarketRow) -> int:
    """Insert or update cross-sectional stats for one (market, trading_date)."""
    country = country_set_for(market=row.market)
    now = datetime.now(timezone.utc)
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                UPSERT_MARKET_SQL[country],
                (
                    row.market,
                    row.trading_date,
                    now,
                    row.momentum_mean,
                    row.momentum_std,
                ),
            )
            affected = cur.rowcount
        conn.commit()

    return affected


def purge_stale_market(database_url: str, retention_days: int) -> int:
    """Delete stale rows from country ``*_market_metrics`` tables (RFC-004)."""
    cutoff = retention_cutoff(retention_days)
    deleted = 0
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for sql in DELETE_STALE_MARKET_SQL:
                cur.execute(sql, (cutoff,))
                deleted += cur.rowcount
        conn.commit()

    return deleted
