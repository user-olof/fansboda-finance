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
TICKER_DELAY_SECONDS = 0.5

UPSERT_SQL = """
INSERT INTO metrics (ticker, trading_date, updated_at, sma_50, sma_200)
VALUES %s
ON CONFLICT (ticker, trading_date) DO UPDATE SET
    sma_50 = EXCLUDED.sma_50,
    sma_200 = EXCLUDED.sma_200,
    updated_at = NOW();
"""


@dataclass(frozen=True)
class MetricRow:
    ticker: str
    trading_date: date
    sma_50: Decimal | None
    sma_200: Decimal | None


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


def fetch_metric_row(ticker: str) -> MetricRow | None:
    """Download history for a ticker and compute SMA metrics."""
    start = datetime.now(timezone.utc).date() - timedelta(days=HISTORY_DAYS)
    history = yf.Ticker(ticker).history(start=start.isoformat(), auto_adjust=True)

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

    return MetricRow(
        ticker=ticker,
        trading_date=trading_date,
        sma_50=sma_50,
        sma_200=sma_200,
    )


def upsert_metrics(database_url: str, rows: list[MetricRow]) -> None:
    """Upsert metric rows into the metrics table."""
    if not rows:
        logger.warning("No rows to upsert")
        return

    now = datetime.now(timezone.utc)
    values = [
        (row.ticker, row.trading_date, now, row.sma_50, row.sma_200)
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

    tickers_path = Path(os.environ.get("TICKERS_FILE", DEFAULT_TICKERS_FILE))

    try:
        tickers = load_tickers(tickers_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    rows: list[MetricRow] = []
    failures = 0

    for i, ticker in enumerate(tickers):
        if i > 0:
            time.sleep(TICKER_DELAY_SECONDS)

        try:
            row = fetch_metric_row(ticker)
            if row is not None:
                rows.append(row)
                logger.info(
                    "Fetched %s: trading_date=%s sma_50=%s sma_200=%s",
                    row.ticker,
                    row.trading_date,
                    row.sma_50,
                    row.sma_200,
                )
        except Exception:
            failures += 1
            logger.exception("Failed to fetch %s", ticker)

    if not rows:
        logger.error("No metrics collected")
        return 1

    try:
        upsert_metrics(database_url, rows)
    except Exception:
        logger.exception("Database upsert failed")
        return 1

    if failures:
        logger.warning("Completed with %d ticker failure(s)", failures)

    return 0


if __name__ == "__main__":
    sys.exit(main())
