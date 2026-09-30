#!/usr/bin/env python3
"""One-off backfill: download 2y history per batch and store one SMA snapshot per week."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from config import get_config
from db.country import CountrySet
from db.metrics import insert_metrics, load_existing_metric_keys
from db.tickers import load_tickers_from_db
from fetch_sma import (
    SMA_200_WINDOW,
    _to_decimal,
    chunked,
    compute_momentum,
    compute_smas,
    trading_date_from_index,
    upsert_market_for_weeks,
)
from models import MetricRow, TickerEntry, week_start_of
from yfinance_client import download_batch, load_currency_for_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

def last_bar_positions_per_week(index: pd.DatetimeIndex) -> list[int]:
    """Return positions of the last bar in each calendar week (Monday-based)."""
    weeks = [week_start_of(pd.Timestamp(ts).date()) for ts in index]
    return [
        pos
        for pos in range(len(weeks))
        if pos == len(weeks) - 1 or weeks[pos + 1] != weeks[pos]
    ]


def metric_rows_from_weekly_samples(
    ticker: str,
    history: pd.DataFrame,
    *,
    company: str | None,
    currency: str | None = None,
) -> list[MetricRow]:
    """Build one SMA snapshot per calendar week from the week's last bar.

    Each snapshot uses only closes up to and including that bar, so it matches
    what the weekly job would have stored had it run after that bar.
    """
    if history.empty or "Close" not in history.columns:
        return []

    close = history["Close"].dropna()
    if close.empty:
        return []

    rows: list[MetricRow] = []
    for pos in last_bar_positions_per_week(close.index):
        window_close = close.iloc[: pos + 1]
        if len(window_close) < SMA_200_WINDOW:
            continue

        sma_50, sma_200 = compute_smas(window_close)
        rows.append(
            MetricRow(
                ticker=ticker,
                company=company,
                trading_date=trading_date_from_index(window_close.index),
                sma_50=sma_50,
                sma_200=sma_200,
                current_price=_to_decimal(window_close.iloc[-1]),
                currency=currency,
                momentum=compute_momentum(sma_50, sma_200),
                z_score=None,
            )
        )

    return rows


def metric_rows_from_backfill_batch(
    data: pd.DataFrame,
    tickers: list[str],
    companies: dict[str, str | None],
    currencies: dict[str, str | None] | None = None,
) -> list[MetricRow]:
    """Parse a batch download into weekly backfill metric rows."""
    if data.empty:
        return []

    currencies = currencies or {}
    rows: list[MetricRow] = []

    if isinstance(data.columns, pd.MultiIndex):
        available = set(data.columns.get_level_values(0))
        for ticker in tickers:
            if ticker not in available:
                logger.warning("No history returned for %s", ticker)
                continue
            ticker_data = data[ticker].dropna(how="all")
            rows.extend(
                metric_rows_from_weekly_samples(
                    ticker,
                    ticker_data,
                    company=companies.get(ticker),
                    currency=currencies.get(ticker),
                )
            )
    elif len(tickers) == 1:
        ticker = tickers[0]
        rows.extend(
            metric_rows_from_weekly_samples(
                ticker,
                data,
                company=companies.get(ticker),
                currency=currencies.get(ticker),
            )
        )

    return rows


def filter_new_rows(
    rows: list[MetricRow], existing: set[tuple[str, object]]
) -> list[MetricRow]:
    """Drop rows whose (ticker, trading_date) already exist in the database.

    Rows for a week that holds an older bar pass through; ``insert_metrics``
    replaces the older bar.
    """
    return [
        row
        for row in rows
        if (row.ticker, row.trading_date) not in existing
    ]


def filter_by_exchange(
    entries: list[TickerEntry],
    exchanges: list[str] | None,
) -> list[TickerEntry]:
    """Keep tickers whose ``exchange_name`` matches one of ``exchanges``.

    Matching is exact but case-insensitive. Returns all entries when
    ``exchanges`` is empty or None.
    """
    if not exchanges:
        return entries
    wanted = {exchange.strip().casefold() for exchange in exchanges}
    return [
        entry
        for entry in entries
        if entry.exchange_name is not None
        and entry.exchange_name.casefold() in wanted
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill SMA history for one country set "
            "(us_metrics / swe_metrics / uk_metrics)"
        ),
    )
    parser.add_argument(
        "--country",
        choices=[c.value for c in CountrySet],
        required=True,
        help="Country set to backfill (us, swe, or uk)",
    )
    parser.add_argument(
        "--exchange",
        action="append",
        metavar="NAME",
        help=(
            "Only backfill tickers whose exchange_name matches NAME "
            "(case-insensitive, e.g. NasdaqGS, NYSE, Stockholm, LSE); "
            "repeat to include several exchanges"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    country = CountrySet(args.country)

    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    database_url = config.database_url
    batch_size = config.backfill_batch_size
    batch_delay = config.backfill_batch_delay_seconds
    max_retries = config.yf_max_retries
    retry_base = config.yf_retry_base_seconds
    name_delay = config.yf_name_delay_seconds
    history_days = config.backfill_history_days

    try:
        watchlist = load_tickers_from_db(database_url, country=country)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to load tickers from database")
        return 1

    if args.exchange:
        selected = filter_by_exchange(watchlist, args.exchange)
        if not selected:
            available = sorted(
                {entry.exchange_name for entry in watchlist if entry.exchange_name}
            )
            logger.error(
                "No %s tickers on exchange(s) %s; available: %s",
                country.value,
                ", ".join(args.exchange),
                ", ".join(available) or "none",
            )
            return 1
        watchlist = selected

    exchange_scope = ",".join(args.exchange) if args.exchange else "all"
    all_tickers = [entry.symbol for entry in watchlist]
    companies = {entry.symbol: entry.company for entry in watchlist}
    start = datetime.now(timezone.utc).date() - timedelta(days=history_days)
    batches = chunked(all_tickers, batch_size)

    total_generated = 0
    total_inserted = 0
    total_skipped_existing = 0
    failed_batches = 0
    week_starts: set[date] = set()

    logger.info(
        "Backfill starting: country=%s exchange=%s tickers=%d batches=%d "
        "history_days=%d",
        country.value,
        exchange_scope,
        len(all_tickers),
        len(batches),
        history_days,
    )

    for i, batch in enumerate(batches):
        logger.info(
            "Fetching batch %d/%d (%d tickers)",
            i + 1,
            len(batches),
            len(batch),
        )
        try:
            existing = load_existing_metric_keys(
                database_url, batch, country=country
            )
            batch_currencies = load_currency_for_tickers(
                batch,
                name_delay=name_delay,
            )
            data = download_batch(
                batch,
                start,
                max_retries=max_retries,
                retry_base_seconds=retry_base,
            )
            batch_rows = metric_rows_from_backfill_batch(
                data,
                batch,
                companies,
                batch_currencies,
            )
            new_rows = filter_new_rows(batch_rows, existing)
            inserted = insert_metrics(database_url, new_rows)
            for row in batch_rows:
                week_starts.add(row.week_start)

            total_generated += len(batch_rows)
            total_inserted += inserted
            total_skipped_existing += len(batch_rows) - len(new_rows)

            logger.info(
                "Batch %d/%d: generated=%d new=%d inserted=%d skipped_existing=%d",
                i + 1,
                len(batches),
                len(batch_rows),
                len(new_rows),
                inserted,
                len(batch_rows) - len(new_rows),
            )
        except Exception:
            failed_batches += 1
            logger.exception(
                "Failed backfill batch %d/%d (%d tickers)",
                i + 1,
                len(batches),
                len(batch),
            )

        if i < len(batches) - 1:
            time.sleep(batch_delay)

    if week_starts:
        try:
            upsert_market_for_weeks(
                database_url,
                week_starts,
                country=country,
            )
        except Exception:
            logger.exception(
                "Failed to upsert %s_market_metrics stats",
                country.value,
            )
            return 1

    logger.info(
        "Backfill summary: country=%s tickers=%d generated=%d inserted=%d "
        "skipped_existing=%d market_weeks=%d failed_batches=%d",
        country.value,
        len(all_tickers),
        total_generated,
        total_inserted,
        total_skipped_existing,
        len(week_starts),
        failed_batches,
    )

    if failed_batches:
        return 1
    if total_generated == 0 and total_skipped_existing == 0:
        logger.error("No metrics generated")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
