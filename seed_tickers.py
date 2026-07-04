#!/usr/bin/env python3
"""Ad-hoc script to seed the tickers watchlist from a symbol file."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import yfinance as yf

from config import DEFAULT_YF_NAME_DELAY_SECONDS, get_config
from db.tickers import upsert_tickers
from fetch_sma import load_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def resolve_name(symbol: str) -> str | None:
    """Fetch company name from yfinance metadata (longName, fallback shortName)."""
    name, _, _ = resolve_ticker_metadata(symbol)
    return name


def resolve_ticker_metadata(
    symbol: str,
) -> tuple[str | None, str | None, str | None]:
    """Fetch name, sector, and industry from yfinance metadata."""
    info = yf.Ticker(symbol).info
    name = info.get("longName") or info.get("shortName")
    sector = info.get("sectorKey") or info.get("sector")
    industry = info.get("industryKey") or info.get("industry")
    if not name:
        logger.warning("No company name found for %s", symbol)
    return (
        str(name) if name else None,
        str(sector) if sector else None,
        str(industry) if industry else None,
    )


def seed_tickers_from_file(
    database_url: str,
    tickers_path: Path,
    *,
    name_delay: float = DEFAULT_YF_NAME_DELAY_SECONDS,
) -> int:
    """Load symbols from file, resolve metadata, upsert into tickers. Returns row count."""
    symbols = load_tickers(tickers_path)
    rows: list[tuple[str, str | None, str | None, str | None]] = []

    for i, symbol in enumerate(symbols):
        if i > 0:
            time.sleep(name_delay)
        try:
            name, sector, industry = resolve_ticker_metadata(symbol)
            rows.append((symbol, name, sector, industry))
            logger.info(
                "Resolved %s: name=%s sector=%s industry=%s",
                symbol,
                name,
                sector,
                industry,
            )
        except Exception:
            logger.exception("Failed to resolve metadata for %s", symbol)
            rows.append((symbol, None, None, None))

    return upsert_tickers(database_url, rows)


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
