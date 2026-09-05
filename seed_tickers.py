#!/usr/bin/env python3
"""Ad-hoc script to seed country tickers tables from a symbol file (RFC-002)."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from config import DEFAULT_YF_NAME_DELAY_SECONDS, get_config
from db.country import infer_listing_market
from db.tickers import TickerUpsertRow, upsert_tickers
from symbols import load_tickers
from yfinance_client import resolve_watchlist_fields

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def resolve_and_upsert_symbols(
    database_url: str,
    symbols: list[str],
    *,
    name_delay: float = DEFAULT_YF_NAME_DELAY_SECONDS,
) -> int:
    """Resolve yfinance metadata and upsert into country tickers tables."""
    rows: list[TickerUpsertRow] = []

    for i, symbol in enumerate(symbols):
        if i > 0:
            time.sleep(name_delay)
        try:
            company, sector, industry, market, exchange_name = (
                resolve_watchlist_fields(symbol)
            )
            rows.append(
                (symbol, company, sector, industry, market, exchange_name)
            )
            logger.info(
                "Resolved %s: company=%s sector=%s industry=%s market=%s "
                "exchange_name=%s",
                symbol,
                company,
                sector,
                industry,
                market,
                exchange_name,
            )
        except Exception:
            logger.exception("Failed to resolve metadata for %s", symbol)
            rows.append(
                (
                    symbol,
                    None,
                    None,
                    None,
                    infer_listing_market(symbol=symbol),
                    None,
                )
            )

    return upsert_tickers(database_url, rows)

def seed_tickers_from_file(
    database_url: str,
    tickers_path: Path,
    *,
    name_delay: float = DEFAULT_YF_NAME_DELAY_SECONDS,
) -> int:
    """Load symbols from file, resolve metadata, upsert country tickers tables."""
    symbols = load_tickers(tickers_path)
    return resolve_and_upsert_symbols(database_url, symbols, name_delay=name_delay)


def main() -> int:
    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    tickers_path = Path(sys.argv[1]) if len(sys.argv) > 1 else config.tickers_file
    name_delay = config.yf_name_delay_seconds

    try:
        count = seed_tickers_from_file(
            config.database_url,
            tickers_path,
            name_delay=name_delay,
        )
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to seed tickers")
        return 1

    logger.info("Seeded %d ticker(s) from %s", count, tickers_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
