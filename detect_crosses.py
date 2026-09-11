#!/usr/bin/env python3
"""Ad-hoc Golden Cross / Death Cross detection from retained ``*_metrics`` (RFC-013).

Reads stored SMA-50/200 history only — no yfinance, not cron-scheduled.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from io import StringIO

from config import get_config
from cross_detection import (
    CrossEvent,
    CrossPattern,
    SmaSnapshot,
    detect_all_patterns,
)
from db.country import CountrySet
from db.metrics import load_sma_history
from symbols import parse_symbols_arg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = (
    "pattern",
    "ticker",
    "country",
    "crossover_date",
    "regime_start_date",
    "regime_weeks",
    "convergence_first_gap",
    "convergence_last_gap",
    "sma_50",
    "sma_200",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Detect completed Golden Cross and Death Cross processes from "
            "retained weekly sma_50 / sma_200 history (no yfinance)"
        ),
    )
    parser.add_argument(
        "--pattern",
        choices=["golden", "death", "all"],
        default="all",
        help="Which pattern(s) to detect (default: all)",
    )
    parser.add_argument(
        "--country",
        choices=[c.value for c in CountrySet],
        default=None,
        help="Limit to one country set (default: us + swe + uk)",
    )
    parser.add_argument(
        "--symbols",
        metavar="SYM1,SYM2",
        help="Comma-separated subset of symbols to scan",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        dest="output_format",
        help="Output format (default: table)",
    )
    return parser


def _patterns_for_arg(value: str) -> list[CrossPattern]:
    if value == "all":
        return [CrossPattern.GOLDEN, CrossPattern.DEATH]
    return [CrossPattern(value)]


def _event_row(event: CrossEvent) -> dict[str, object]:
    return {
        "pattern": event.pattern.value,
        "ticker": event.ticker,
        "country": event.country,
        "crossover_date": event.crossover_date.isoformat(),
        "regime_start_date": event.regime_start_date.isoformat(),
        "regime_weeks": event.regime_weeks,
        "convergence_first_gap": str(event.convergence_first_gap),
        "convergence_last_gap": str(event.convergence_last_gap),
        "sma_50": str(event.sma_50),
        "sma_200": str(event.sma_200),
    }


def format_events(events: list[CrossEvent], output_format: str) -> str:
    """Render detection events as table, JSON, or CSV text."""
    rows = [_event_row(event) for event in events]
    if output_format == "json":
        return json.dumps(rows, indent=2) + "\n"
    if output_format == "csv":
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()

    if not rows:
        return "(no cross detections)\n"

    # Human-readable aligned table.
    str_rows = [
        {key: str(row[key]) for key in OUTPUT_COLUMNS} for row in rows
    ]
    widths = {
        key: max(len(key), *(len(row[key]) for row in str_rows))
        for key in OUTPUT_COLUMNS
    }
    header = "  ".join(key.ljust(widths[key]) for key in OUTPUT_COLUMNS)
    sep = "  ".join("-" * widths[key] for key in OUTPUT_COLUMNS)
    lines = [header, sep]
    for row in str_rows:
        lines.append(
            "  ".join(row[key].ljust(widths[key]) for key in OUTPUT_COLUMNS)
        )
    return "\n".join(lines) + "\n"


def collect_cross_events(
    database_url: str,
    *,
    patterns: list[CrossPattern],
    country: CountrySet | None,
    symbols: list[str] | None,
    min_regime_weeks: int,
    convergence_weeks: int,
) -> list[CrossEvent]:
    """Load SMA history and run pure detection for the requested scope."""
    countries = [country] if country is not None else list(CountrySet)
    events: list[CrossEvent] = []

    for set_key in countries:
        history = load_sma_history(
            database_url, country=set_key, symbols=symbols
        )
        for ticker, rows in history.items():
            snapshots = [
                SmaSnapshot(trading_date, sma_50, sma_200)
                for trading_date, sma_50, sma_200 in rows
            ]
            events.extend(
                detect_all_patterns(
                    snapshots,
                    patterns=patterns,
                    ticker=ticker,
                    country=set_key.value,
                    min_regime_weeks=min_regime_weeks,
                    convergence_weeks=convergence_weeks,
                )
            )

    events.sort(
        key=lambda e: (e.crossover_date, e.country, e.ticker, e.pattern.value)
    )
    return events


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    symbols = parse_symbols_arg(args.symbols) if args.symbols else None
    if args.symbols is not None and not symbols:
        logger.error("No symbols provided")
        return 1

    country = CountrySet(args.country) if args.country else None
    patterns = _patterns_for_arg(args.pattern)

    try:
        events = collect_cross_events(
            config.database_url,
            patterns=patterns,
            country=country,
            symbols=symbols,
            min_regime_weeks=config.cross_min_regime_weeks,
            convergence_weeks=config.cross_convergence_weeks,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to detect crosses")
        return 1

    sys.stdout.write(format_events(events, args.output_format))
    logger.info("Detected %d cross event(s)", len(events))
    return 0


if __name__ == "__main__":
    sys.exit(main())
