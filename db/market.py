"""Database access for the country market_metrics tables (RFC-001)."""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg2

from db.country import CountrySet, country_set_for
from db.metrics import retention_cutoff
from models import MarketRow

UPSERT_MARKET_SQL = {
    CountrySet.US: """
INSERT INTO us_market_metrics (
    market, trading_date, updated_at,
    raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (market, trading_date) DO UPDATE SET
    updated_at = EXCLUDED.updated_at,
    raw_mean_50 = EXCLUDED.raw_mean_50,
    raw_mean_200 = EXCLUDED.raw_mean_200,
    raw_std_50 = EXCLUDED.raw_std_50,
    raw_std_200 = EXCLUDED.raw_std_200
""",
    CountrySet.SWE: """
INSERT INTO swe_market_metrics (
    market, trading_date, updated_at,
    raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (market, trading_date) DO UPDATE SET
    updated_at = EXCLUDED.updated_at,
    raw_mean_50 = EXCLUDED.raw_mean_50,
    raw_mean_200 = EXCLUDED.raw_mean_200,
    raw_std_50 = EXCLUDED.raw_std_50,
    raw_std_200 = EXCLUDED.raw_std_200
""",
    CountrySet.UK: """
INSERT INTO uk_market_metrics (
    market, trading_date, updated_at,
    raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (market, trading_date) DO UPDATE SET
    updated_at = EXCLUDED.updated_at,
    raw_mean_50 = EXCLUDED.raw_mean_50,
    raw_mean_200 = EXCLUDED.raw_mean_200,
    raw_std_50 = EXCLUDED.raw_std_50,
    raw_std_200 = EXCLUDED.raw_std_200
""",
}

DELETE_STALE_MARKET_SQL = (
    "DELETE FROM us_market_metrics WHERE trading_date < %s",
    "DELETE FROM swe_market_metrics WHERE trading_date < %s",
    "DELETE FROM uk_market_metrics WHERE trading_date < %s",
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
                    row.raw_mean_50,
                    row.raw_mean_200,
                    row.raw_std_50,
                    row.raw_std_200,
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
