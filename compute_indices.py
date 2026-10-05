#!/usr/bin/env python3
"""Compute equal-weighted weekly market and sector indices into ``indices`` (PRD §5.8).

Per country set: the market index (US-IDX / SWE-IDX / UK-IDX) and one index per
sector (e.g. US-IDX-TECHNOLOGY), each storing price, SMA-50 and SMA-200 levels
(chained by the plain average of the members' stored weekly growth in that
measure), momentum, pct_uptrend, currency, and — for sector rows — a z-score vs
the set's other sectors (RFC-018). Stock-weeks with implausible growth are
excluded and logged (FR-37b). No yfinance calls. Runs standalone (full rebuild
by default) and from ``fetch_sma.py`` for the weeks it wrote.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from config import (
    DEFAULT_OUTLIER_MAX_GROWTH,
    DEFAULT_OUTLIER_MIN_GROWTH,
    get_config,
)
from db.country import CountrySet
from db.indices import write_index_weeks
from db.metrics import load_distinct_week_starts
from db.outliers import load_outliers

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
    max_growth: float = DEFAULT_OUTLIER_MAX_GROWTH,
    min_growth: float = DEFAULT_OUTLIER_MIN_GROWTH,
) -> int:
    """Recompute market and sector indices; returns rows written.

    ``week_starts=None`` rebuilds every index from its earliest stored metrics
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
            database_url,
            weeks,
            country=set_key,
            rebuild=week_starts is None,
            max_growth=max_growth,
            min_growth=min_growth,
        )
        outliers = load_outliers(
            database_url,
            weeks,
            country=set_key,
            max_growth=max_growth,
            min_growth=min_growth,
        )
        if week_starts is None:
            outliers = [o for o in outliers if o.week_start != weeks[0]]
        for outlier in outliers:
            logger.warning(
                "Outlier excluded from %s indices: %s trading_date=%s "
                "price_growth=%s sma_50_growth=%s sma_200_growth=%s (%s)",
                set_key.value,
                outlier.ticker,
                outlier.trading_date.isoformat(),
                outlier.price_growth,
                outlier.sma_50_growth,
                outlier.sma_200_growth,
                outlier.bound,
            )
        if outliers:
            logger.info(
                "Indices %s: %d outlier stock-week(s) excluded",
                set_key.value,
                len(outliers),
            )
        market_rows = [row for row in rows if row.sector_key is None]
        for row in market_rows:
            logger.info(
                "Index %s trading_date=%s ticker_count=%d current_price=%.4f "
                "sma_50=%.4f sma_200=%.4f momentum=%s pct_uptrend=%s",
                row.ticker,
                row.trading_date.isoformat(),
                row.ticker_count,
                row.current_price,
                row.sma_50,
                row.sma_200,
                "n/a" if row.momentum is None else f"{row.momentum:.6f}",
                "n/a" if row.pct_uptrend is None else f"{row.pct_uptrend:.1f}",
            )
        logger.info(
            "Indices %s: wrote %d market and %d sector row(s) for %d week(s)",
            set_key.value,
            len(market_rows),
            len(rows) - len(market_rows),
            len(weeks),
        )
        written += len(rows)

    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild equal-weighted weekly market and sector indices (US-IDX / "
            "SWE-IDX / UK-IDX and their sectors) from stored metrics (no yfinance)"
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
        written = refresh_indices(
            config.database_url,
            None,
            country=country,
            max_growth=config.outlier_max_growth,
            min_growth=config.outlier_min_growth,
        )
    except Exception:
        logger.exception("Failed to compute indices (%s)", scope)
        return 1

    logger.info("Summary: country=%s index_rows=%d", scope, written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
