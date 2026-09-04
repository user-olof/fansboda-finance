#!/usr/bin/env python3
"""One-off: recompute us_market_metrics / swe_market_metrics from stored metrics."""

from __future__ import annotations

import logging
import sys

from config import get_config
from db.metrics import load_distinct_trading_dates
from fetch_sma import upsert_market_for_trading_dates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    database_url = config.database_url

    try:
        trading_dates = load_distinct_trading_dates(database_url)
    except Exception:
        logger.exception("Failed to load trading dates from us_metrics / swe_metrics")
        return 1

    if not trading_dates:
        logger.error("No metrics trading dates found in us_metrics / swe_metrics")
        return 1

    logger.info(
        "Backfilling us_/swe_market_metrics for %d trading date(s)",
        len(trading_dates),
    )

    try:
        upsert_market_for_trading_dates(database_url, set(trading_dates))
    except Exception:
        logger.exception("Failed to upsert us_/swe_market_metrics stats")
        return 1

    logger.info(
        "Market_metrics backfill summary: trading_dates=%d",
        len(trading_dates),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
