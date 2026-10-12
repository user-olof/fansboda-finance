#!/usr/bin/env python3
"""Ad-hoc script to seed country tickers tables from a symbol file (RFC-002).

``--update-business-summary`` is a one-off mode: fill ``business_summary`` for
tickers already in the database without touching their other columns.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from config import DEFAULT_YF_NAME_DELAY_SECONDS, get_config
from db.country import CountrySet, country_set_for, infer_listing_market
from db.tickers import (
    TickerUpsertRow,
    load_tickers_from_db,
    update_business_summaries,
    upsert_tickers,
)
from symbols import load_tickers
from yfinance_client import resolve_business_summary, resolve_watchlist_fields

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def filter_symbols_for_country(
    symbols: list[str],
    country: CountrySet | None,
) -> list[str]:
    """Return symbols that route to ``country``, or all symbols when unset."""
    if country is None:
        return symbols
    return [symbol for symbol in symbols if country_set_for(symbol=symbol) is country]


def resolve_and_upsert_symbols(
    database_url: str,
    symbols: list[str],
    *,
    name_delay: float = DEFAULT_YF_NAME_DELAY_SECONDS,
    country: CountrySet | None = None,
) -> int:
    """Resolve yfinance metadata and upsert into country tickers tables.

    When ``country`` is set, skip symbols that do not route to that set before
    any yfinance calls (PRD FR-11).
    """
    symbols = filter_symbols_for_country(symbols, country)
    rows: list[TickerUpsertRow] = []

    for i, symbol in enumerate(symbols):
        if i > 0:
            time.sleep(name_delay)
        try:
            company, sector, industry, market, exchange_name, business_summary = (
                resolve_watchlist_fields(symbol)
            )
            rows.append(
                (
                    symbol,
                    company,
                    sector,
                    industry,
                    market,
                    exchange_name,
                    business_summary,
                )
            )
            logger.info(
                "Resolved %s: company=%s sector=%s industry=%s market=%s "
                "exchange_name=%s business_summary_chars=%d",
                symbol,
                company,
                sector,
                industry,
                market,
                exchange_name,
                len(business_summary or ""),
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
                    None,
                )
            )

    return upsert_tickers(database_url, rows)


def seed_tickers_from_file(
    database_url: str,
    tickers_path: Path,
    *,
    name_delay: float = DEFAULT_YF_NAME_DELAY_SECONDS,
    country: CountrySet | None = None,
) -> int:
    """Load symbols from file, resolve metadata, upsert country tickers tables."""
    symbols = load_tickers(tickers_path)
    return resolve_and_upsert_symbols(
        database_url,
        symbols,
        name_delay=name_delay,
        country=country,
    )


def update_business_summaries_from_db(
    database_url: str,
    *,
    name_delay: float = DEFAULT_YF_NAME_DELAY_SECONDS,
    country: CountrySet | None = None,
) -> tuple[int, int]:
    """Resolve ``business_summary`` for every stored ticker and update it.

    Only ``business_summary`` (and ``updated_at``) change. Tickers whose
    yfinance lookup fails are left untouched. Returns ``(updated, failed)``.
    """
    entries = load_tickers_from_db(database_url, country=country)
    summaries = []
    failed = 0

    for i, entry in enumerate(entries):
        if i > 0:
            time.sleep(name_delay)
        try:
            summary = resolve_business_summary(entry.symbol)
        except Exception:
            failed += 1
            logger.exception("Failed to resolve business summary for %s", entry.symbol)
            continue
        if summary is None:
            logger.warning("No business summary found for %s", entry.symbol)
        else:
            logger.info(
                "Resolved business summary for %s (%d chars)",
                entry.symbol,
                len(summary),
            )
        summaries.append((entry, summary))

    return update_business_summaries(database_url, summaries), failed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Seed us_tickers / swe_tickers / uk_tickers from a symbol file"
        ),
    )
    parser.add_argument(
        "tickers_file",
        nargs="?",
        help="Symbol file path (default: TICKERS_FILE from config)",
    )
    parser.add_argument(
        "--country",
        choices=[c.value for c in CountrySet],
        help=(
            "Only resolve/upsert symbols that route to this country set "
            "(us, swe, or uk)"
        ),
    )
    parser.add_argument(
        "--update-business-summary",
        action="store_true",
        help=(
            "One-off: fill business_summary for tickers already in the "
            "database (ignores tickers_file; other columns unchanged)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    tickers_path = Path(args.tickers_file) if args.tickers_file else config.tickers_file
    name_delay = config.yf_name_delay_seconds
    country = CountrySet(args.country) if args.country else None

    if args.update_business_summary:
        try:
            updated, failed = update_business_summaries_from_db(
                config.database_url,
                name_delay=name_delay,
                country=country,
            )
        except ValueError as exc:
            logger.error("%s", exc)
            return 1
        except Exception:
            logger.exception("Failed to update business summaries")
            return 1
        logger.info(
            "Business summary update: scope=%s updated=%d failed=%d",
            country.value if country is not None else "us+swe+uk",
            updated,
            failed,
        )
        return 0

    try:
        count = seed_tickers_from_file(
            config.database_url,
            tickers_path,
            name_delay=name_delay,
            country=country,
        )
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to seed tickers")
        return 1

    if country is not None:
        logger.info(
            "Seeded %d ticker(s) from %s (country=%s)",
            count,
            tickers_path,
            country.value,
        )
    else:
        logger.info("Seeded %d ticker(s) from %s", count, tickers_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
