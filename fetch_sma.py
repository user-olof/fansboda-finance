#!/usr/bin/env python3
"""Fetch weekly SMA metrics from yfinance and append to Neon Postgres."""

from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import yfinance as yf

from config import (
    DEFAULT_YF_MAX_RETRIES,
    DEFAULT_YF_RETRY_BASE_SECONDS,
    get_config,
)
from db.metrics import filter_stale_tickers, insert_metrics, purge_stale_metrics
from db.tickers import load_tickers_from_db
from models import MetricRow, TickerEntry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

HISTORY_DAYS = 300
SMA_50_WINDOW = 50
SMA_200_WINDOW = 200


def load_tickers(path: Path) -> list[str]:
    """Read ticker symbols from a text file, one per line."""
    if not path.exists():
        raise FileNotFoundError(f"Tickers file not found: {path}")

    tickers: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tickers.append(stripped.upper())

    if not tickers:
        raise ValueError(f"No tickers found in {path}")

    return tickers


def chunked(items: list[str], size: int) -> list[list[str]]:
    """Split a list into fixed-size chunks."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def compute_smas(close: pd.Series) -> tuple[Decimal | None, Decimal | None]:
    """Compute 50-day and 200-day simple moving averages from close prices."""
    if close.empty:
        return None, None

    sma_50 = close.rolling(SMA_50_WINDOW).mean().iloc[-1]
    sma_200 = close.rolling(SMA_200_WINDOW).mean().iloc[-1]

    return (
        _to_decimal(sma_50),
        _to_decimal(sma_200),
    )


def _to_decimal(value: object) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return Decimal(str(round(float(value), 6)))


def trading_date_from_index(index: pd.DatetimeIndex) -> date:
    """Return the calendar date of the most recent bar."""
    ts = index[-1]
    if hasattr(ts, "date"):
        return ts.date()
    return pd.Timestamp(ts).date()


def resolve_currency(symbol: str) -> str | None:
    """Fetch listing currency from yfinance metadata."""
    info = yf.Ticker(symbol).info
    currency = info.get("currency")
    return str(currency) if currency else None


def load_currency_for_tickers(
    tickers: list[str],
    *,
    name_delay: float,
) -> dict[str, str | None]:
    """Resolve yfinance currency for each ticker with rate-limit delay."""
    currencies: dict[str, str | None] = {}

    for i, symbol in enumerate(tickers):
        if i > 0:
            time.sleep(name_delay)
        try:
            currencies[symbol] = resolve_currency(symbol)
        except Exception:
            logger.exception("Failed to resolve currency for %s", symbol)
            currencies[symbol] = None

    return currencies


def metric_row_from_history(
    ticker: str,
    history: pd.DataFrame,
    *,
    company: str | None = None,
    currency: str | None = None,
) -> MetricRow | None:
    """Compute SMA metrics from a single ticker's OHLCV history."""
    if history.empty:
        logger.warning("No history returned for %s", ticker)
        return None

    close = history["Close"].dropna()
    if len(close) < SMA_200_WINDOW:
        logger.warning(
            "Skipping %s: only %d closes (need %d for SMA 200)",
            ticker,
            len(close),
            SMA_200_WINDOW,
        )
        return None

    sma_50, sma_200 = compute_smas(close)
    trading_date = trading_date_from_index(history.index)
    current_price = _to_decimal(close.iloc[-1])

    return MetricRow(
        ticker=ticker,
        company=company,
        trading_date=trading_date,
        sma_50=sma_50,
        sma_200=sma_200,
        current_price=current_price,
        currency=currency,
    )


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("429", "too many requests", "rate", "timeout", "connection")
    )


def download_batch(
    tickers: list[str],
    start: date,
    *,
    max_retries: int = DEFAULT_YF_MAX_RETRIES,
    retry_base_seconds: float = DEFAULT_YF_RETRY_BASE_SECONDS,
) -> pd.DataFrame:
    """Download OHLCV history for a batch of tickers with retry/backoff."""
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            data = yf.download(
                tickers,
                start=start.isoformat(),
                auto_adjust=True,
                group_by="ticker",
                progress=False,
                threads=False,
            )
            if data.empty:
                raise ValueError(
                    f"Empty dataframe returned for batch of {len(tickers)} ticker(s)"
                )
            return data
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            if not _is_retryable(exc) and not isinstance(exc, ValueError):
                break
            delay = retry_base_seconds * (2**attempt)
            logger.warning(
                "Batch download failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                max_retries + 1,
                delay,
                exc,
            )
            time.sleep(delay)

    assert last_exc is not None
    raise last_exc


def metric_rows_from_batch(
    data: pd.DataFrame,
    tickers: list[str],
    companies: dict[str, str | None],
    currencies: dict[str, str | None] | None = None,
) -> list[MetricRow]:
    """Parse a yfinance batch download into MetricRow objects."""
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
            row = metric_row_from_history(
                ticker,
                ticker_data,
                company=companies.get(ticker),
                currency=currencies.get(ticker),
            )
            if row is not None:
                rows.append(row)
    elif len(tickers) == 1:
        ticker = tickers[0]
        row = metric_row_from_history(
            ticker,
            data,
            company=companies.get(ticker),
            currency=currencies.get(ticker),
        )
        if row is not None:
            rows.append(row)

    return rows


def _run_retention_purge(database_url: str, retention_days: int) -> int:
    purged = purge_stale_metrics(database_url, retention_days)
    logger.info(
        "Retention purge: deleted %d row(s) older than %d days",
        purged,
        retention_days,
    )
    return purged


def main() -> int:
    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    database_url = config.database_url
    batch_size = config.yf_batch_size
    batch_delay = config.yf_batch_delay_seconds
    name_delay = config.yf_name_delay_seconds
    max_retries = config.yf_max_retries
    retry_base = config.yf_retry_base_seconds
    retention_days = config.metrics_retention_days

    try:
        watchlist = load_tickers_from_db(database_url)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except Exception:
        logger.exception("Failed to load tickers from database")
        return 1

    all_tickers = [entry.symbol for entry in watchlist]
    companies = {entry.symbol: entry.company for entry in watchlist}

    try:
        stale_tickers, skipped_count, max_date = filter_stale_tickers(
            database_url, all_tickers
        )
    except Exception:
        logger.exception("Failed to query stale tickers from database")
        return 1

    if max_date is not None and skipped_count:
        logger.info(
            "Skipping %d tickers already up to date (trading_date=%s)",
            skipped_count,
            max_date,
        )

    if not stale_tickers:
        logger.info(
            "All %d tickers already up to date, nothing to fetch",
            len(all_tickers),
        )
        try:
            purged = _run_retention_purge(database_url, retention_days)
        except Exception:
            logger.exception("Retention purge failed")
            return 1
        logger.info(
            "Summary: total=%d skipped=%d fetched=0 inserted=0 purged=%d failed_batches=0",
            len(all_tickers),
            skipped_count,
            purged,
        )
        return 0

    start = datetime.now(timezone.utc).date() - timedelta(days=HISTORY_DAYS)
    batches = chunked(stale_tickers, batch_size)
    fetched_count = 0
    inserted_count = 0
    failed_batches = 0

    for i, batch in enumerate(batches):
        logger.info(
            "Fetching batch %d/%d (%d tickers)",
            i + 1,
            len(batches),
            len(batch),
        )
        try:
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
            batch_rows = metric_rows_from_batch(
                data, batch, companies, currencies=batch_currencies
            )
            fetched_count += len(batch_rows)
            for row in batch_rows:
                logger.info(
                    "Fetched %s (%s): trading_date=%s currency=%s current_price=%s "
                    "sma_50=%s sma_200=%s",
                    row.ticker,
                    row.company,
                    row.trading_date,
                    row.currency,
                    row.current_price,
                    row.sma_50,
                    row.sma_200,
                )
            batch_inserted = insert_metrics(database_url, batch_rows)
            inserted_count += batch_inserted
            logger.info(
                "Batch %d/%d: fetched=%d inserted=%d",
                i + 1,
                len(batches),
                len(batch_rows),
                batch_inserted,
            )
        except Exception:
            failed_batches += 1
            logger.exception(
                "Failed batch %d/%d (%d tickers)",
                i + 1,
                len(batches),
                len(batch),
            )

        if i < len(batches) - 1:
            time.sleep(batch_delay)

    try:
        purged = _run_retention_purge(database_url, retention_days)
    except Exception:
        logger.exception("Retention purge failed")
        return 1

    logger.info(
        "Summary: total=%d skipped=%d fetched=%d inserted=%d purged=%d "
        "failed_batches=%d http_batches=%d",
        len(all_tickers),
        skipped_count,
        fetched_count,
        inserted_count,
        purged,
        failed_batches,
        len(batches),
    )

    if fetched_count == 0:
        logger.error("No metrics collected")
        return 1

    if failed_batches:
        logger.warning("Completed with %d failed batch(es)", failed_batches)

    return 0


if __name__ == "__main__":
    sys.exit(main())
