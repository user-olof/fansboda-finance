#!/usr/bin/env python3
"""One-off backfill: download 2y history per batch and insert weekly SMA snapshots."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from config import DEFAULT_BACKFILL_WINDOW_WEEKS, get_config
from db.metrics import insert_metrics, load_existing_metric_keys
from db.tickers import load_tickers_from_db
from fetch_sma import (
    SMA_200_WINDOW,
    _to_decimal,
    chunked,
    compute_smas,
    download_batch,
    trading_date_from_index,
)
from models import MetricRow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

def week_index_series(index: pd.DatetimeIndex, anchor: pd.Timestamp) -> pd.Series:
    """Map each bar to a week number counting forward from the anchor date."""
    normalized = pd.to_datetime(index).normalize()
    return ((normalized - anchor).days // 7).astype(int)


def sample_start_weeks(max_week: int, window_weeks: int) -> list[int]:
    """Return week-0 offsets for rolling windows [s, s + window_weeks - 1]."""
    if max_week < window_weeks - 1:
        return []
    last_start = max_week - (window_weeks - 1)
    return list(range(0, last_start + 1))


def metric_rows_from_weekly_samples(
    ticker: str,
    history: pd.DataFrame,
    *,
    name: str | None,
    window_weeks: int = DEFAULT_BACKFILL_WINDOW_WEEKS,
) -> list[MetricRow]:
    """Build SMA snapshots from rolling week windows anchored at the oldest bar."""
    if history.empty or "Close" not in history.columns:
        return []

    close = history["Close"].dropna()
    if close.empty:
        return []

    anchor = pd.Timestamp(trading_date_from_index(pd.DatetimeIndex([close.index.min()])))
    week_idx = week_index_series(close.index, anchor)
    max_week = int(week_idx.max())
    rows: list[MetricRow] = []

    for start_week in sample_start_weeks(max_week, window_weeks):
        end_week = start_week + window_weeks - 1
        window_close = close[(week_idx >= start_week) & (week_idx <= end_week)]
        if len(window_close) < SMA_200_WINDOW:
            logger.debug(
                "Skipping %s window weeks %d-%d: only %d closes",
                ticker,
                start_week,
                end_week,
                len(window_close),
            )
            continue

        sma_50, sma_200 = compute_smas(window_close)
        trading_date = trading_date_from_index(window_close.index)
        rows.append(
            MetricRow(
                ticker=ticker,
                name=name,
                trading_date=trading_date,
                sma_50=sma_50,
                sma_200=sma_200,
                current_price=_to_decimal(window_close.iloc[-1]),
            )
        )

    return rows


def metric_rows_from_backfill_batch(
    data: pd.DataFrame,
    tickers: list[str],
    names: dict[str, str | None],
    *,
    window_weeks: int = DEFAULT_BACKFILL_WINDOW_WEEKS,
) -> list[MetricRow]:
    """Parse a batch download into backfill metric rows for all rolling windows."""
    if data.empty:
        return []

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
                    name=names.get(ticker),
                    window_weeks=window_weeks,
                )
            )
    elif len(tickers) == 1:
        rows.extend(
            metric_rows_from_weekly_samples(
                tickers[0],
                data,
                name=names.get(tickers[0]),
                window_weeks=window_weeks,
            )
        )

    return rows


def filter_new_rows(
    rows: list[MetricRow], existing: set[tuple[str, object]]
) -> list[MetricRow]:
    """Drop rows whose (ticker, trading_date) already exist in the database."""
    return [
        row
        for row in rows
        if (row.ticker, row.trading_date) not in existing
    ]


def main() -> int:
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
    history_days = config.backfill_history_days
    window_weeks = config.backfill_window_weeks

    try:
        watchlist = load_tickers_from_db(database_url)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to load tickers from database")
        return 1

    all_tickers = [entry.symbol for entry in watchlist]
    names = {entry.symbol: entry.name for entry in watchlist}
    start = datetime.now(timezone.utc).date() - timedelta(days=history_days)
    batches = chunked(all_tickers, batch_size)

    total_generated = 0
    total_inserted = 0
    total_skipped_existing = 0
    failed_batches = 0

    logger.info(
        "Backfill starting: tickers=%d batches=%d history_days=%d window_weeks=%d",
        len(all_tickers),
        len(batches),
        history_days,
        window_weeks,
    )

    for i, batch in enumerate(batches):
        logger.info(
            "Fetching batch %d/%d (%d tickers)",
            i + 1,
            len(batches),
            len(batch),
        )
        try:
            existing = load_existing_metric_keys(database_url, batch)
            data = download_batch(
                batch,
                start,
                max_retries=max_retries,
                retry_base_seconds=retry_base,
            )
            batch_rows = metric_rows_from_backfill_batch(
                data,
                batch,
                names,
                window_weeks=window_weeks,
            )
            new_rows = filter_new_rows(batch_rows, existing)
            inserted = insert_metrics(database_url, new_rows)

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

    logger.info(
        "Backfill summary: tickers=%d generated=%d inserted=%d "
        "skipped_existing=%d failed_batches=%d",
        len(all_tickers),
        total_generated,
        total_inserted,
        total_skipped_existing,
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
