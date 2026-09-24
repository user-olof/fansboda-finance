#!/usr/bin/env python3
"""Dev-only: truncate us_/swe_/uk_ market_metrics, metrics, and tickers.

Refuses to run when APP_ENV is prod/production. Not for production use.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow `pipenv run python scripts/truncate_dev_tables.py` from repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import get_config, require_non_production
from db.truncate import truncate_dev_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    try:
        require_non_production()
        config = get_config()
        truncate_dev_tables(config.database_url)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to truncate tables")
        return 1

    logger.info("Truncated us_/swe_/uk_ market_metrics, metrics, and tickers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
