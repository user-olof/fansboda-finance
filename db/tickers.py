"""Database access for the tickers watchlist table."""

from __future__ import annotations

import psycopg2
from psycopg2.extras import execute_values

from models import TickerEntry

LOAD_TICKERS_SQL = """
SELECT symbol, name FROM tickers ORDER BY symbol
"""

UPSERT_TICKER_SQL = """
INSERT INTO tickers (symbol, name)
VALUES %s
ON CONFLICT (symbol) DO UPDATE SET
    name = EXCLUDED.name,
    updated_at = NOW();
"""


def load_tickers_from_db(database_url: str) -> list[TickerEntry]:
    """Load the watchlist from the tickers table."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(LOAD_TICKERS_SQL)
            rows = cur.fetchall()

    if not rows:
        raise ValueError("No tickers found in tickers table")

    return [TickerEntry(symbol=row[0], name=row[1]) for row in rows]


def upsert_tickers(database_url: str, rows: list[tuple[str, str | None]]) -> int:
    """Upsert ticker symbols and names. Returns rows affected."""
    if not rows:
        return 0

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            execute_values(cur, UPSERT_TICKER_SQL, rows)
            affected = cur.rowcount
        conn.commit()

    return affected
