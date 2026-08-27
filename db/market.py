"""Database access for the market table."""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg2

from db.metrics import retention_cutoff
from models import MarketRow

UPSERT_MARKET_SQL = """
INSERT INTO market (
    trading_date, updated_at,
    raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (trading_date) DO UPDATE SET
    updated_at = EXCLUDED.updated_at,
    raw_mean_50 = EXCLUDED.raw_mean_50,
    raw_mean_200 = EXCLUDED.raw_mean_200,
    raw_std_50 = EXCLUDED.raw_std_50,
    raw_std_200 = EXCLUDED.raw_std_200
"""

DELETE_STALE_MARKET_SQL = """
DELETE FROM market
WHERE trading_date < %s
"""


def upsert_market_stats(database_url: str, row: MarketRow) -> int:
    """Insert or update cross-sectional stats for one trading_date."""
    now = datetime.now(timezone.utc)
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                UPSERT_MARKET_SQL,
                (
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
    """Delete market rows older than retention_days (UTC). Returns rows deleted."""
    cutoff = retention_cutoff(retention_days)
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DELETE_STALE_MARKET_SQL, (cutoff,))
            deleted = cur.rowcount
        conn.commit()

    return deleted
