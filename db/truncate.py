"""Dev-only table truncation helpers."""

from __future__ import annotations

import psycopg2

TRUNCATE_DEV_TABLES_SQL = """
TRUNCATE TABLE
    us_market_metrics, swe_market_metrics,
    us_metrics, swe_metrics,
    us_tickers, swe_tickers
RESTART IDENTITY
"""


def truncate_dev_tables(database_url: str) -> None:
    """Truncate all country-set tables (dev use only)."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(TRUNCATE_DEV_TABLES_SQL)
        conn.commit()
