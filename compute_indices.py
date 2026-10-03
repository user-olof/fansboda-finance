#!/usr/bin/env python3
"""Compute equal-weighted weekly country indices into ``indices`` (PRD §5.8).

US-IDX / SWE-IDX / UK-IDX store price, SMA-50 and SMA-200 levels (each chained
by the plain average of the stocks' weekly growth in that measure) plus
momentum, from ``*_metrics``. No yfinance calls. Runs standalone (full rebuild
by default) and from ``fetch_sma.py`` for the weeks it wrote.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from config import get_config
from db.country import CountrySet
from db.indices import write_index_weeks
from db.metrics import load_distinct_week_starts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def refresh_indices(
    database_url: str,
    week_starts: list[date] | None = None,
    *,
    country: CountrySet | None = None,
) -> int:
    """Recompute country indices; returns rows written.

    ``week_starts=None`` rebuilds each index from its earliest stored metrics
    week (price base = 100). Otherwise every stored metrics week from the earliest
    given week onward is recomputed, so later rows stay chained correctly.
    """
    countries = [country] if country is not None else list(CountrySet)
    written = 0
    for set_key in countries:
        stored_weeks = load_distinct_week_starts(database_url, country=set_key)
        if week_starts is None:
            weeks = stored_weeks
        elif week_starts:
            start = min(week_starts)
            weeks = [week for week in stored_weeks if week >= start]
        else:
            weeks = []
        if not weeks:
            continue

        rows = write_index_weeks(
            database_url, weeks, country=set_key, rebuild=week_starts is None
        )
        for row in rows:
            logger.info(
                "Index %s trading_date=%s ticker_count=%d current_price=%.4f "
                "sma_50=%.4f sma_200=%.4f momentum=%s",
                row.ticker,
                row.trading_date.isoformat(),
                row.ticker_count,
                row.current_price,
                row.sma_50,
                row.sma_200,
                "n/a" if row.momentum is None else f"{row.momentum:.6f}",
            )
        written += len(rows)

    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild equal-weighted weekly country indices (US-IDX / SWE-IDX / "
            "UK-IDX) from stored metrics (no yfinance)"
        ),
    )
    parser.add_argument(
        "--country",
        choices=[c.value for c in CountrySet],
        default=None,
        help="Limit to one country set (default: us + swe + uk)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    country = CountrySet(args.country) if args.country else None

    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    scope = country.value if country is not None else "us+swe+uk"
    logger.info("Rebuilding indices (country=%s)", scope)

    try:
        written = refresh_indices(config.database_url, None, country=country)
    except Exception:
        logger.exception("Failed to compute indices (%s)", scope)
        return 1

    logger.info("Summary: country=%s index_rows=%d", scope, written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
