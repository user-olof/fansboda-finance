#!/usr/bin/env python3
"""Ad-hoc script to seed the tickers watchlist from a symbol file."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import psycopg2
import yfinance as yf
from dotenv import load_dotenv
from psycopg2.extras import execute_values

from fetch_sma import DEFAULT_TICKERS_FILE, _config_float, load_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_YF_NAME_DELAY_SECONDS = 0.25

UPSERT_TICKER_SQL = """
INSERT INTO tickers (symbol, name)
VALUES %s
ON CONFLICT (symbol) DO UPDATE SET
    name = EXCLUDED.name;
"""


def company_name_from_ticker(symbol: str) -> str | None:
    """Fetch company name from yfinance metadata."""
    info = yf.Ticker(symbol).info
    name = info.get("longName") or info.get("shortName")
    if not name:
        logger.warning("No company name found for %s", symbol)
        return None
    return str(name)


def upsert_tickers(database_url: str, rows: list[tuple[str, str | None]]) -> None:
    """Upsert ticker symbols and names into the tickers table."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            execute_values(cur, UPSERT_TICKER_SQL, rows)
        conn.commit()


def main() -> int:
    load_dotenv()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not set")
        return 1

    default_path = Path(os.environ.get("TICKERS_FILE", DEFAULT_TICKERS_FILE))
    tickers_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_path
    name_delay = _config_float("YF_NAME_DELAY_SECONDS", DEFAULT_YF_NAME_DELAY_SECONDS)

    try:
        symbols = load_tickers(tickers_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    rows: list[tuple[str, str | None]] = []
    for i, symbol in enumerate(symbols):
        if i > 0:
            time.sleep(name_delay)
        try:
            name = company_name_from_ticker(symbol)
            rows.append((symbol, name))
            logger.info("Resolved %s: %s", symbol, name)
        except Exception:
            logger.exception("Failed to resolve name for %s", symbol)
            rows.append((symbol, None))

    try:
        upsert_tickers(database_url, rows)
    except Exception:
        logger.exception("Failed to upsert tickers")
        return 1

    logger.info("Seeded %d ticker(s) from %s", len(rows), tickers_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
