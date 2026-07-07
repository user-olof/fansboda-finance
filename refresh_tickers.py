#!/usr/bin/env python3
"""Ad-hoc script to refresh watchlist metadata (FR-12, RFC-010)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config import get_config
from db.tickers import load_tickers_from_db
from seed_tickers import resolve_and_upsert_symbols
from symbols import load_tickers, parse_symbols_arg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _load_file_symbols(tickers_path: Path) -> list[str]:
    try:
        return load_tickers(tickers_path)
    except (FileNotFoundError, ValueError):
        return []


def _load_db_symbols(database_url: str) -> list[str]:
    try:
        return [entry.symbol for entry in load_tickers_from_db(database_url)]
    except ValueError:
        return []


def load_symbols_for_refresh(
    database_url: str,
    *,
    tickers_path: Path,
    from_db: bool = False,
    symbols: list[str] | None = None,
) -> list[str]:
    """Return the deduplicated symbol list to refresh."""
    if symbols is not None:
        if not symbols:
            raise ValueError("No symbols provided")
        return sorted({symbol.upper() for symbol in symbols})

    if from_db:
        db_symbols = _load_db_symbols(database_url)
        if not db_symbols:
            raise ValueError("No tickers found in tickers table")
        return sorted(db_symbols)

    merged = sorted(
        set(_load_file_symbols(tickers_path)) | set(_load_db_symbols(database_url))
    )
    if not merged:
        raise ValueError("No tickers to refresh (empty file and database)")
    return merged


def refresh_tickers(
    database_url: str,
    symbols: list[str],
    *,
    name_delay: float,
) -> int:
    """Resolve and upsert watchlist metadata for the given symbols."""
    return resolve_and_upsert_symbols(
        database_url,
        symbols,
        name_delay=name_delay,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh tickers metadata (company, sector, industry)",
    )
    parser.add_argument(
        "tickers_file",
        nargs="?",
        help="Symbol file path (default: TICKERS_FILE from config)",
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Refresh all symbols already in the tickers table",
    )
    parser.add_argument(
        "--symbols",
        metavar="SYM1,SYM2",
        help="Comma-separated subset of symbols to refresh",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.from_db and args.symbols:
        parser.error("use either --from-db or --symbols, not both")

    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    tickers_path = Path(args.tickers_file) if args.tickers_file else config.tickers_file
    symbol_arg = parse_symbols_arg(args.symbols) if args.symbols else None
    name_delay = config.yf_name_delay_seconds

    try:
        symbols = load_symbols_for_refresh(
            config.database_url,
            tickers_path=tickers_path,
            from_db=args.from_db,
            symbols=symbol_arg,
        )
        count = refresh_tickers(
            config.database_url,
            symbols,
            name_delay=name_delay,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to refresh tickers")
        return 1

    logger.info("Refreshed %d ticker(s)", count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
