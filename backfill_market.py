#!/usr/bin/env python3
"""One-off: recompute momentum, market aggregates, and z_scores from stored SMAs.

Derives ``momentum`` from ``sma_50 / sma_200`` on existing ``*_metrics`` rows,
upserts ``*_market_metrics`` (``momentum_mean`` / ``momentum_std``), then sets
``z_score``. No yfinance calls — safe after migrate_momentum_zscore.sql.
"""

from __future__ import annotations

import argparse
import logging
import sys

from config import get_config
from db.country import CountrySet
from db.metrics import load_distinct_trading_dates, recompute_momentum_from_smas
from fetch_sma import upsert_market_for_trading_dates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute momentum, market aggregates, and z_scores from stored "
            "SMA columns (no yfinance)"
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

    database_url = config.database_url
    scope = country.value if country is not None else "us+swe+uk"

    try:
        momentum_updated = recompute_momentum_from_smas(
            database_url, country=country
        )
    except Exception:
        logger.exception("Failed to recompute momentum from SMAs (%s)", scope)
        return 1

    logger.info("Recomputed momentum on %d %s metrics row(s)", momentum_updated, scope)

    try:
        trading_dates = load_distinct_trading_dates(
            database_url, country=country
        )
    except Exception:
        logger.exception("Failed to load trading dates (%s)", scope)
        return 1

    if not trading_dates:
        logger.error("No metrics trading dates found for %s", scope)
        return 1

    logger.info(
        "Upserting market aggregates and z_scores for %d trading date(s) (%s)",
        len(trading_dates),
        scope,
    )

    try:
        upsert_market_for_trading_dates(
            database_url, set(trading_dates), country=country
        )
    except Exception:
        logger.exception("Failed to upsert market stats / z_scores (%s)", scope)
        return 1

    logger.info(
        "Derived-metrics recompute summary: scope=%s momentum_rows=%d "
        "trading_dates=%d",
        scope,
        momentum_updated,
        len(trading_dates),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
