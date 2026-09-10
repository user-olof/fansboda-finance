#!/usr/bin/env python3
"""Detect Golden Cross patterns from stored Neon metrics history (RFC-013).

Reads weekly ``sma_50`` / ``sma_200`` snapshots from ``us_metrics`` /
``swe_metrics`` / ``uk_metrics``. No yfinance calls.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from typing import Iterable, TextIO

from config import get_config
from db.country import CountrySet
from db.metrics import load_sma_history
from golden_cross import (
    GoldenCrossEvent,
    GoldenCrossParams,
    detect_golden_crosses,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Detect Golden Cross events from stored SMA-50/200 history "
            "(no live market APIs)"
        ),
    )
    parser.add_argument(
        "--country",
        choices=[c.value for c in CountrySet],
        default=None,
        help="Limit to one country set (default: us + swe + uk)",
    )
    parser.add_argument(
        "--tickers",
        default=None,
        help="Comma-separated symbols to scan (default: all in scope)",
    )
    parser.add_argument(
        "--min-below-weeks",
        type=int,
        default=None,
        help=(
            "Minimum consecutive weeks with sma_50 < sma_200 before a cross "
            "(default: config / 4)"
        ),
    )
    parser.add_argument(
        "--convergence-weeks",
        type=int,
        default=None,
        help=(
            "Lookback weeks for gap narrowing before the cross "
            "(default: config / 3; must be <= min-below-weeks)"
        ),
    )
    parser.add_argument(
        "--format",
        choices=("table", "json", "csv"),
        default="table",
        help="Output format (default: table)",
    )
    return parser


def _parse_tickers(raw: str | None) -> list[str] | None:
    if raw is None or not raw.strip():
        return None
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def _event_row(event: GoldenCrossEvent) -> dict[str, object]:
    return {
        "ticker": event.ticker,
        "country": event.country,
        "trading_date": event.trading_date.isoformat(),
        "sma_50": str(event.sma_50),
        "sma_200": str(event.sma_200),
        "weeks_below": event.weeks_below,
        "gap_at_below_start": str(event.gap_at_below_start),
        "gap_before_cross": str(event.gap_before_cross),
        "converged": event.converged,
        "stages": [
            {
                "trading_date": stage.trading_date.isoformat(),
                "stage": stage.stage.value,
                "sma_50": str(stage.sma_50),
                "sma_200": str(stage.sma_200),
                "gap": str(stage.gap),
            }
            for stage in event.stages
        ],
    }


def format_events_table(events: Iterable[GoldenCrossEvent], out: TextIO) -> None:
    rows = list(events)
    if not rows:
        out.write("No golden-cross events found.\n")
        return

    header = (
        f"{'ticker':<16} {'country':<7} {'cross_date':<12} "
        f"{'sma_50':>12} {'sma_200':>12} {'weeks_below':>11} "
        f"{'gap_start':>12} {'gap_pre':>12}"
    )
    out.write(header + "\n")
    out.write("-" * len(header) + "\n")
    for event in rows:
        out.write(
            f"{event.ticker:<16} {event.country:<7} "
            f"{event.trading_date.isoformat():<12} "
            f"{event.sma_50:>12} {event.sma_200:>12} "
            f"{event.weeks_below:>11} "
            f"{event.gap_at_below_start:>12} {event.gap_before_cross:>12}\n"
        )


def format_events_json(events: Iterable[GoldenCrossEvent], out: TextIO) -> None:
    payload = [_event_row(event) for event in events]
    json.dump(payload, out, indent=2)
    out.write("\n")


def format_events_csv(events: Iterable[GoldenCrossEvent], out: TextIO) -> None:
    writer = csv.DictWriter(
        out,
        fieldnames=[
            "ticker",
            "country",
            "trading_date",
            "sma_50",
            "sma_200",
            "weeks_below",
            "gap_at_below_start",
            "gap_before_cross",
            "converged",
        ],
    )
    writer.writeheader()
    for event in events:
        row = _event_row(event)
        writer.writerow({key: row[key] for key in writer.fieldnames})


def collect_events(
    database_url: str,
    *,
    country: CountrySet | None,
    tickers: list[str] | None,
    params: GoldenCrossParams,
) -> list[GoldenCrossEvent]:
    history = load_sma_history(
        database_url, country=country, tickers=tickers
    )
    events: list[GoldenCrossEvent] = []
    for (set_key, ticker), series in sorted(
        history.items(), key=lambda item: (item[0][0].value, item[0][1])
    ):
        events.extend(
            detect_golden_crosses(
                series,
                ticker=ticker,
                country=set_key.value,
                params=params,
            )
        )
    events.sort(key=lambda e: (e.trading_date, e.country, e.ticker))
    return events


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    country = CountrySet(args.country) if args.country else None
    tickers = _parse_tickers(args.tickers)

    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    min_below = (
        args.min_below_weeks
        if args.min_below_weeks is not None
        else config.golden_cross_min_below_weeks
    )
    convergence = (
        args.convergence_weeks
        if args.convergence_weeks is not None
        else config.golden_cross_convergence_weeks
    )

    try:
        params = GoldenCrossParams(
            min_below_weeks=min_below,
            convergence_weeks=convergence,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    scope = country.value if country is not None else "us+swe+uk"
    logger.info(
        "Scanning golden crosses: scope=%s tickers=%s "
        "min_below_weeks=%d convergence_weeks=%d",
        scope,
        ",".join(tickers) if tickers else "all",
        params.min_below_weeks,
        params.convergence_weeks,
    )

    try:
        events = collect_events(
            config.database_url,
            country=country,
            tickers=tickers,
            params=params,
        )
    except Exception:
        logger.exception("Failed to detect golden crosses (%s)", scope)
        return 1

    logger.info("Found %d golden-cross event(s) (%s)", len(events), scope)

    if args.format == "json":
        format_events_json(events, sys.stdout)
    elif args.format == "csv":
        format_events_csv(events, sys.stdout)
    else:
        format_events_table(events, sys.stdout)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
