"""yfinance lookups and batch OHLCV downloads with retry and rate limiting."""

from __future__ import annotations

import logging
import time
from datetime import date

import pandas as pd
import yfinance as yf

from config import DEFAULT_YF_MAX_RETRIES, DEFAULT_YF_RETRY_BASE_SECONDS

logger = logging.getLogger(__name__)


def _fetch_info(symbol: str) -> dict:
    return yf.Ticker(symbol).info


def _listing_market_from_info(info: dict, *, symbol: str) -> str | None:
    market = info.get("market")
    if not market:
        logger.warning("No listing market found for %s", symbol)
        return None
    return str(market)


def _watchlist_fields_from_info(
    info: dict,
    *,
    symbol: str,
) -> tuple[str | None, str | None, str | None, str | None]:
    company = info.get("longName") or info.get("shortName")
    sector = info.get("sectorKey") or info.get("sector")
    industry = info.get("industryKey") or info.get("industry")
    if not company:
        logger.warning("No company name found for %s", symbol)
    return (
        str(company) if company else None,
        str(sector) if sector else None,
        str(industry) if industry else None,
        _listing_market_from_info(info, symbol=symbol),
    )


def resolve_name(symbol: str) -> str | None:
    """Fetch company name from yfinance metadata (longName, fallback shortName)."""
    company, _, _, _ = _watchlist_fields_from_info(_fetch_info(symbol), symbol=symbol)
    return company


def resolve_metadata(symbol: str) -> tuple[str | None, str | None]:
    """Fetch sector and industry from yfinance metadata."""
    _, sector, industry, _ = _watchlist_fields_from_info(
        _fetch_info(symbol), symbol=symbol
    )
    return sector, industry


def resolve_watchlist_fields(
    symbol: str,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Resolve company, sector, industry, and listing market in one yfinance lookup."""
    return _watchlist_fields_from_info(_fetch_info(symbol), symbol=symbol)


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
