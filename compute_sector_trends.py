#!/usr/bin/env python3
"""Compute equal-weighted weekly trend averages per sector (PRD §5.7).

Reads ``*_metrics`` joined to ``*_tickers.sector`` and replaces rows in
``us_by_sector`` / ``swe_by_sector`` / ``uk_by_sector``. No yfinance calls.
Runs standalone (all stored weeks by default) and from ``fetch_sma.py`` for
the weeks the weekly job just wrote.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from config import get_config
from db.country import CountrySet
from db.metrics import load_distinct_week_starts
from db.sector import prune_orphan_sector_weeks, refresh_sector_weeks
from models import week_start_of

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def refresh_sector_trends(
    database_url: str,
    week_starts: list[date] | None = None,
    *,
    country: CountrySet | None = None,
) -> tuple[int, int]:
    """Recompute sector trends and prune weeks no longer in metrics.

    ``week_starts=None`` recomputes every week stored in each country's
    metrics table. Returns ``(rows_written, rows_pruned)``.
    """
    countries = [country] if country is not None else list(CountrySet)
    written = 0
    pruned = 0
    for set_key in countries:
        weeks = (
            load_distinct_week_starts(database_url, country=set_key)
            if week_starts is None
            else sorted(set(week_starts))
        )
        if weeks:
            written += refresh_sector_weeks(database_url, weeks, country=set_key)
        pruned += prune_orphan_sector_weeks(database_url, country=set_key)

    return written, pruned


def _parse_week(value: str) -> date:
    try:
        return week_start_of(date.fromisoformat(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r} (expected YYYY-MM-DD)"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compute equal-weighted weekly trend averages per sector into "
            "*_by_sector (no yfinance)"
        ),
    )
    parser.add_argument(
        "--country",
        choices=[c.value for c in CountrySet],
        default=None,
        help="Limit to one country set (default: us + swe + uk)",
    )
    parser.add_argument(
        "--week",
        type=_parse_week,
        default=None,
        metavar="YYYY-MM-DD",
        help="Only recompute the week containing this date (default: all stored weeks)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    country = CountrySet(args.country) if args.country else None
    week_starts = [args.week] if args.week is not None else None

    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    scope = country.value if country is not None else "us+swe+uk"
    weeks_label = args.week.isoformat() if args.week is not None else "all"
    logger.info("Computing sector trends (country=%s week=%s)", scope, weeks_label)

    try:
        written, pruned = refresh_sector_trends(
            config.database_url, week_starts, country=country
        )
    except Exception:
        logger.exception("Failed to compute sector trends (%s)", scope)
        return 1

    logger.info(
        "Summary: country=%s week=%s sector_rows=%d pruned=%d",
        scope,
        weeks_label,
        written,
        pruned,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
