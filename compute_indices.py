#!/usr/bin/env python3
"""One-off manual initialization of the equal-weighted indices (never cron).

Per country set: the market index (US-IDX / SWE-IDX / UK-IDX) and one index per
sector (e.g. US-IDX-TECHNOLOGY). Downloads daily history, sets each index's
start levels — price 100 on INDEX_START_DATE (or, with fewer than
INDEX_MIN_COMPONENTS listed members, on the first later week-end that has
them) and SMA-50 / SMA-200 from the index's reconstructed daily price — and
writes the full weekly series chained from the stored weekly growth
(specs/001-index-initial-sma). A country is only replaced when every index it
already has got its start levels. The weekly update lives in ``fetch_sma.py``.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from config import get_config
from db.country import CountrySet
from db.indices import load_index_tickers, write_index_weeks
from db.metrics import load_distinct_week_starts
from db.outliers import load_outliers
from db.tickers import load_tickers_from_db
from fetch_sma import log_excluded_outliers, log_market_rows
from index_anchor import AnchorSettings, compute_anchors
from models import week_start_of

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _initialize_country(
    database_url: str, country: CountrySet, settings: AnchorSettings
) -> int | None:
    """Initialize one country; rows written, or None when it was left unchanged."""
    started = time.monotonic()
    start_week = week_start_of(settings.start_date)
    weeks = [
        week
        for week in load_distinct_week_starts(database_url, country=country)
        if week >= start_week
    ]
    if not weeks:
        logger.warning(
            "Indices %s: no stored metrics from %s on; nothing to initialize",
            country.value,
            start_week.isoformat(),
        )
        return 0

    entries = load_tickers_from_db(database_url, country=country)
    result = compute_anchors(
        entries, country, settings=settings, first_stored_week=weeks[0]
    )
    stored = load_index_tickers(database_url, country)
    missing = sorted(stored - set(result.anchors) - result.below_minimum)
    if missing or not result.anchors:
        logger.error(
            "Indices %s left unchanged: no start levels for %s",
            country.value,
            ", ".join(missing) or "any index",
        )
        return None

    written = write_index_weeks(
        database_url,
        weeks,
        country=country,
        rebuild=True,
        start_week=start_week,
        anchors=result.anchors,
        max_growth=settings.max_growth,
        min_growth=settings.min_growth,
    )
    for anchor in sorted(result.anchors.values(), key=lambda a: a.ticker):
        levels = anchor.levels
        logger.info(
            "Index %s start_date=%s anchor_week=%s sma_50=%s sma_200=%s "
            "momentum=%.6f days_used=%d",
            anchor.ticker,
            anchor.start_date.isoformat(),
            anchor.week_start.isoformat(),
            levels.sma_50,
            levels.sma_200,
            levels.sma_50 / levels.sma_200,
            anchor.days_used,
        )
    log_market_rows(logger, written.rows)
    outliers = load_outliers(
        database_url,
        weeks,
        country=country,
        max_growth=settings.max_growth,
        min_growth=settings.min_growth,
    )
    log_excluded_outliers(logger, country, outliers)
    market_rows = sum(1 for row in written.rows if row.sector_key is None)
    logger.info(
        "Indices %s: anchors=%d not_started=%d missing_stocks=%d market_rows=%d "
        "sector_rows=%d weeks=%d elapsed=%.0fs",
        country.value,
        len(result.anchors),
        len(result.below_minimum),
        len(result.missing_symbols),
        market_rows,
        len(written.rows) - market_rows,
        len(weeks),
        time.monotonic() - started,
    )
    return len(written.rows)


def initialize_indices(
    database_url: str,
    *,
    country: CountrySet | None = None,
    settings: AnchorSettings,
) -> tuple[int, list[CountrySet]]:
    """Initialize every (or one) country; returns rows written and failed countries."""
    countries = [country] if country is not None else list(CountrySet)
    written = 0
    failed: list[CountrySet] = []
    for set_key in countries:
        rows = _initialize_country(database_url, set_key, settings)
        if rows is None:
            failed.append(set_key)
        else:
            written += rows
    return written, failed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "One-off manual initialization (never cron): downloads daily data, "
            "sets the index start levels on INDEX_START_DATE, and writes the full "
            "weekly series of the market and sector indices (US-IDX / SWE-IDX / "
            "UK-IDX and their sectors)"
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

    settings = AnchorSettings.from_config(config)
    scope = country.value if country is not None else "us+swe+uk"
    logger.info(
        "Initializing indices (country=%s start_date=%s)",
        scope,
        settings.start_date.isoformat(),
    )

    try:
        written, failed = initialize_indices(
            config.database_url, country=country, settings=settings
        )
    except Exception:
        logger.exception("Failed to initialize indices (%s)", scope)
        return 1

    logger.info(
        "Summary: country=%s index_rows=%d failed=%s",
        scope,
        written,
        ",".join(c.value for c in failed) or "none",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
