#!/usr/bin/env python3
"""Fetch daily SMA metrics from yfinance and upsert into Neon Postgres."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg2
import yfinance as yf
from dotenv import load_dotenv
from psycopg2.extras import execute_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_TICKERS_FILE = Path(__file__).parent / "tickers.txt"
HISTORY_DAYS = 300
SMA_50_WINDOW = 50
SMA_200_WINDOW = 200
DEFAULT_YF_BATCH_SIZE = 40
DEFAULT_YF_BATCH_DELAY_SECONDS = 2.0
DEFAULT_YF_MAX_RETRIES = 3
DEFAULT_YF_RETRY_BASE_SECONDS = 5.0

UPSERT_SQL = """
INSERT INTO metrics (ticker, name, trading_date, updated_at, sma_50, sma_200, current_price)
VALUES %s
ON CONFLICT (ticker) DO UPDATE SET
    name = EXCLUDED.name,
    trading_date = EXCLUDED.trading_date,
    sma_50 = EXCLUDED.sma_50,
    sma_200 = EXCLUDED.sma_200,
    current_price = EXCLUDED.current_price,
    updated_at = NOW();
"""

FRESH_TICKERS_SQL = """
SELECT ticker
FROM metrics
WHERE ticker = ANY(%s)
  AND trading_date = (SELECT MAX(trading_date) FROM metrics)
"""

LOAD_TICKERS_SQL = """
SELECT symbol, name FROM tickers ORDER BY symbol
"""


@dataclass(frozen=True)
class TickerEntry:
    symbol: str
    name: str | None


@dataclass(frozen=True)
class MetricRow:
    ticker: str
    name: str | None
    trading_date: date
    sma_50: Decimal | None
    sma_200: Decimal | None
    current_price: Decimal | None


def _config_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


def _config_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return float(raw)


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


def load_tickers_from_db(database_url: str) -> list[TickerEntry]:
    """Load the watchlist from the tickers table."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(LOAD_TICKERS_SQL)
            rows = cur.fetchall()

    if not rows:
        raise ValueError("No tickers found in tickers table")

    return [TickerEntry(symbol=row[0], name=row[1]) for row in rows]


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


def metric_row_from_history(
    ticker: str,
    history: pd.DataFrame,
    *,
    name: str | None = None,
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
        name=name,
        trading_date=trading_date,
        sma_50=sma_50,
        sma_200=sma_200,
        current_price=current_price,
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
    names: dict[str, str | None],
) -> list[MetricRow]:
    """Parse a yfinance batch download into MetricRow objects."""
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
            row = metric_row_from_history(
                ticker, ticker_data, name=names.get(ticker)
            )
            if row is not None:
                rows.append(row)
    elif len(tickers) == 1:
        row = metric_row_from_history(
            tickers[0], data, name=names.get(tickers[0])
        )
        if row is not None:
            rows.append(row)

    return rows


def filter_stale_tickers(
    database_url: str, tickers: list[str]
) -> tuple[list[str], int, date | None]:
    """Return tickers that need fetching; skip those already at max trading_date."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(trading_date) FROM metrics")
            max_row = cur.fetchone()

            if not max_row or max_row[0] is None:
                return tickers, 0, None

            max_date = max_row[0]
            cur.execute(FRESH_TICKERS_SQL, (tickers,))
            fresh = {row[0] for row in cur.fetchall()}

    stale = [ticker for ticker in tickers if ticker not in fresh]
    skipped = len(tickers) - len(stale)
    return stale, skipped, max_date


def upsert_metrics(database_url: str, rows: list[MetricRow]) -> None:
    """Upsert metric rows into the metrics table."""
    if not rows:
        logger.warning("No rows to upsert")
        return

    now = datetime.now(timezone.utc)
    values = [
        (
            row.ticker,
            row.name,
            row.trading_date,
            now,
            row.sma_50,
            row.sma_200,
            row.current_price,
        )
        for row in rows
    ]

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            execute_values(cur, UPSERT_SQL, values)
        conn.commit()

    logger.info("Upserted %d row(s)", len(rows))


def main() -> int:
    load_dotenv()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not set")
        return 1

    batch_size = _config_int("YF_BATCH_SIZE", DEFAULT_YF_BATCH_SIZE)
    batch_delay = _config_float("YF_BATCH_DELAY_SECONDS", DEFAULT_YF_BATCH_DELAY_SECONDS)
    max_retries = _config_int("YF_MAX_RETRIES", DEFAULT_YF_MAX_RETRIES)
    retry_base = _config_float("YF_RETRY_BASE_SECONDS", DEFAULT_YF_RETRY_BASE_SECONDS)

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
        return 0

    start = datetime.now(timezone.utc).date() - timedelta(days=HISTORY_DAYS)
    batches = chunked(stale_tickers, batch_size)
    rows: list[MetricRow] = []
    failed_batches = 0

    for i, batch in enumerate(batches):
        logger.info(
            "Fetching batch %d/%d (%d tickers)",
            i + 1,
            len(batches),
            len(batch),
        )
        try:
            data = download_batch(
                batch,
                start,
                max_retries=max_retries,
                retry_base_seconds=retry_base,
            )
            batch_rows = metric_rows_from_batch(data, batch, names)
            rows.extend(batch_rows)
            for row in batch_rows:
                logger.info(
                    "Fetched %s (%s): trading_date=%s current_price=%s "
                    "sma_50=%s sma_200=%s",
                    row.ticker,
                    row.name,
                    row.trading_date,
                    row.current_price,
                    row.sma_50,
                    row.sma_200,
                )
        except Exception:
            failed_batches += 1
            logger.exception(
                "Failed to fetch batch %d/%d (%d tickers)",
                i + 1,
                len(batches),
                len(batch),
            )

        if i < len(batches) - 1:
            time.sleep(batch_delay)

    logger.info(
        "Summary: total=%d skipped=%d fetched=%d failed_batches=%d http_batches=%d",
        len(all_tickers),
        skipped_count,
        len(rows),
        failed_batches,
        len(batches),
    )

    if not rows:
        logger.error("No metrics collected")
        return 1

    try:
        upsert_metrics(database_url, rows)
    except Exception:
        logger.exception("Database upsert failed")
        return 1

    if failed_batches:
        logger.warning("Completed with %d failed batch(es)", failed_batches)

    return 0


if __name__ == "__main__":
    sys.exit(main())
