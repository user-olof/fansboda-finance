#!/usr/bin/env python3
"""Weekly SMA fetch into us_metrics / swe_metrics / uk_metrics (RFC-003).

Loads us_tickers + swe_tickers + uk_tickers, skips fresh symbols per country
metrics table, batch-downloads OHLCV, appends SMA snapshots, upserts
us_/swe_/uk_market_metrics, and purges stale history.
"""

from __future__ import annotations

import logging
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd

from compute_indices import refresh_indices
from compute_sector_trends import refresh_sector_trends
from config import BaseConfig, get_config
from db.country import CountrySet, country_set_for
from db.market import upsert_market_stats
from db.metrics import (
    filter_stale_tickers,
    insert_metrics,
    load_momentum_by_market_for_week,
    update_z_scores_for_week,
)
from db.outliers import load_outliers
from db.retention import purge_stale_data
from db.tickers import load_tickers_from_db
from gmail_client import send_email
from models import MarketRow, MetricRow, OutlierRow, week_start_of
from outlier_email import build_outlier_email
from yfinance_client import download_batch, load_currency_for_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

HISTORY_DAYS = 300
SMA_50_WINDOW = 50
SMA_200_WINDOW = 200


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


def previous_week_bar_position(index: pd.DatetimeIndex, pos: int) -> int | None:
    """Position of the last bar in the calendar week before the bar at ``pos``."""
    previous_week = week_start_of(pd.Timestamp(index[pos]).date()) - timedelta(days=7)
    for candidate in range(pos - 1, -1, -1):
        week = week_start_of(pd.Timestamp(index[candidate]).date())
        if week == previous_week:
            return candidate
        if week < previous_week:
            return None
    return None


def _growth(current: object, previous: object) -> Decimal | None:
    if current is None or previous is None:
        return None
    previous_value = float(previous)
    current_value = float(current)
    if previous_value == 0 or pd.isna(previous_value) or pd.isna(current_value):
        return None
    return _to_decimal(current_value / previous_value - 1)


def compute_weekly_growth(
    close: pd.Series, pos: int
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Growth of close, SMA-50 and SMA-200 vs the previous calendar week (FR-5a).

    Both ends come from the same (consistently adjusted) ``close`` series, each
    SMA using only closes up to its own bar.
    """
    previous_pos = previous_week_bar_position(close.index, pos)
    if previous_pos is None:
        return None, None, None
    sma_50, sma_200 = compute_smas(close.iloc[: pos + 1])
    prev_sma_50, prev_sma_200 = compute_smas(close.iloc[: previous_pos + 1])
    return (
        _growth(close.iloc[pos], close.iloc[previous_pos]),
        _growth(sma_50, prev_sma_50),
        _growth(sma_200, prev_sma_200),
    )


def compute_momentum(
    sma_50: Decimal | None,
    sma_200: Decimal | None,
) -> Decimal | None:
    """Return sma_50 / sma_200; None when inputs are missing or sma_200 is zero."""
    if sma_50 is None or sma_200 is None or sma_200 == 0:
        return None
    return _to_decimal(float(sma_50) / float(sma_200))


def compute_z_score(
    momentum: Decimal | None,
    momentum_mean: Decimal | None,
    momentum_std: Decimal | None,
) -> Decimal | None:
    """Return (momentum - mean) / std; None when inputs missing or std is zero."""
    if (
        momentum is None
        or momentum_mean is None
        or momentum_std is None
        or momentum_std == 0
    ):
        return None
    return _to_decimal((float(momentum) - float(momentum_mean)) / float(momentum_std))


def _mean_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return _to_decimal(sum(float(value) for value in values) / len(values))


def _population_std_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    if len(values) == 1:
        return Decimal("0")
    return _to_decimal(statistics.pstdev(float(value) for value in values))


def aggregate_market_stats(
    week_start: date,
    market: str,
    momentum_values: list[Decimal],
) -> MarketRow | None:
    """Build cross-sectional market stats for one (market, week_start)."""
    if not momentum_values:
        return None

    return MarketRow(
        market=market,
        week_start=week_start,
        momentum_mean=_mean_decimal(momentum_values),
        momentum_std=_population_std_decimal(momentum_values),
    )


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
    momentum = compute_momentum(sma_50, sma_200)
    price_growth, sma_50_growth, sma_200_growth = compute_weekly_growth(
        close, len(close) - 1
    )

    return MetricRow(
        ticker=ticker,
        company=company,
        trading_date=trading_date,
        sma_50=sma_50,
        sma_200=sma_200,
        current_price=current_price,
        currency=currency,
        momentum=momentum,
        z_score=None,
        price_growth=price_growth,
        sma_50_growth=sma_50_growth,
        sma_200_growth=sma_200_growth,
    )


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


def upsert_market_for_weeks(
    database_url: str,
    week_starts: set[date],
    *,
    country: CountrySet | None = None,
) -> None:
    """Recompute market aggregates and z_scores for each week.

    When ``country`` is set, only upsert aggregates / z_scores for that
    country set (FR-18).
    """
    for week_start in sorted(week_starts):
        by_market = load_momentum_by_market_for_week(database_url, week_start)
        if not by_market:
            logger.warning(
                "No momentum values available for market stats in week %s",
                week_start,
            )
            continue

        for market, momentum_values in sorted(
            by_market.items(),
            key=lambda item: (item[0] is None, item[0] or ""),
        ):
            if market is None:
                logger.warning(
                    "Skipping market stats for tickers without listing market "
                    "in week %s",
                    week_start,
                )
                continue

            if country is not None and country_set_for(market=market) is not country:
                continue

            market_row = aggregate_market_stats(
                week_start,
                market,
                momentum_values,
            )
            if market_row is None:
                continue

            upsert_market_stats(database_url, market_row)
            logger.info(
                "Market stats for %s week %s: momentum_mean=%s momentum_std=%s "
                "(n=%d)",
                market,
                week_start,
                market_row.momentum_mean,
                market_row.momentum_std,
                len(momentum_values),
            )

        update_z_scores_for_week(database_url, week_start, country=country)


def _run_retention_purge(
    database_url: str, retention_days: int
) -> tuple[int, int, int]:
    metrics_purged, market_metrics_purged, indices_purged = purge_stale_data(
        database_url, retention_days
    )
    logger.info(
        "Retention purge: deleted %d us_/swe_/uk_ metrics, %d us_/swe_/uk_ "
        "market_metrics, and %d indices row(s) older than %d days",
        metrics_purged,
        market_metrics_purged,
        indices_purged,
        retention_days,
    )
    return metrics_purged, market_metrics_purged, indices_purged


def _run_sector_trends(database_url: str, week_starts: set[date]) -> None:
    written, pruned = refresh_sector_trends(database_url, sorted(week_starts))
    logger.info(
        "Sector trends: wrote %d us_/swe_/uk_ by_sector row(s) for %d week(s), "
        "pruned %d orphan row(s)",
        written,
        len(week_starts),
        pruned,
    )


def _run_indices(config: BaseConfig, week_starts: set[date]) -> None:
    written = refresh_indices(
        config.database_url,
        sorted(week_starts),
        max_growth=config.outlier_max_growth,
        min_growth=config.outlier_min_growth,
    )
    logger.info(
        "Indices: wrote %d US-IDX/SWE-IDX/UK-IDX row(s) from week(s) %s",
        written,
        ", ".join(week.isoformat() for week in sorted(week_starts)),
    )


def _run_outlier_email(config: BaseConfig, week_starts: set[date]) -> tuple[int, int]:
    """Email newly detected outliers in the weeks written (FR-7c / §5.9).

    Never raises: email problems must not fail the run (FR-50). Returns
    ``(new, continuing)`` outlier counts.
    """
    try:
        outliers: list[OutlierRow] = []
        for country in CountrySet:
            outliers.extend(
                load_outliers(
                    config.database_url,
                    sorted(week_starts),
                    country=country,
                    max_growth=config.outlier_max_growth,
                    min_growth=config.outlier_min_growth,
                )
            )
    except Exception:
        logger.exception("Failed to load outliers for the data-quality email")
        return 0, 0

    new_count = sum(1 for row in outliers if row.is_new)
    continuing = len(outliers) - new_count
    message = build_outlier_email(
        outliers,
        max_growth=config.outlier_max_growth,
        min_growth=config.outlier_min_growth,
        now=datetime.now(timezone.utc),
    )
    if message is None:
        logger.info(
            "Outlier email: no new outliers (%d continuing), nothing to send",
            continuing,
        )
        return new_count, continuing

    subject, body = message
    if not config.alert_email_enabled:
        logger.info(
            "Outlier email disabled (ALERT_EMAIL_ENABLED off); would send:\n%s\n\n%s",
            subject,
            body,
        )
        return new_count, continuing
    if not config.alert_email_from or not config.alert_email_to:
        logger.error(
            "Outlier email enabled but ALERT_EMAIL_FROM / ALERT_EMAIL_TO missing; "
            "not sent:\n%s\n\n%s",
            subject,
            body,
        )
        return new_count, continuing

    try:
        message_id = send_email(
            sender=config.alert_email_from,
            recipient=config.alert_email_to,
            subject=subject,
            body=body,
            max_retries=config.yf_max_retries,
            retry_base_seconds=config.yf_retry_base_seconds,
        )
    except Exception:
        logger.exception(
            "Failed to send outlier email; outliers were:\n%s\n\n%s", subject, body
        )
        return new_count, continuing

    logger.info(
        "Outlier email sent (%d new outlier(s), message id %s)",
        new_count,
        message_id,
    )
    return new_count, continuing


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
        stale_tickers, skipped_count, week_start = filter_stale_tickers(
            database_url, all_tickers
        )
    except Exception:
        logger.exception("Failed to query stale tickers from database")
        return 1

    if skipped_count:
        logger.info(
            "Skipping %d tickers already holding the latest bar for week %s",
            skipped_count,
            week_start,
        )

    if not stale_tickers:
        logger.info(
            "All %d tickers already up to date, nothing to fetch",
            len(all_tickers),
        )
        try:
            metrics_purged, market_metrics_purged, indices_purged = (
                _run_retention_purge(database_url, retention_days)
            )
        except Exception:
            logger.exception("Retention purge failed")
            return 1
        try:
            _run_sector_trends(database_url, set())
        except Exception:
            logger.exception("Failed to compute sector trends")
            return 1
        logger.info(
            "Summary: total=%d skipped=%d fetched=0 inserted=0 "
            "purged_metrics=%d purged_market_metrics=%d purged_indices=%d "
            "failed_batches=0",
            len(all_tickers),
            skipped_count,
            metrics_purged,
            market_metrics_purged,
            indices_purged,
        )
        return 0

    start = datetime.now(timezone.utc).date() - timedelta(days=HISTORY_DAYS)
    batches = chunked(stale_tickers, batch_size)
    fetched_count = 0
    inserted_count = 0
    failed_batches = 0
    week_starts: set[date] = set()

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
                week_starts.add(row.week_start)
                logger.info(
                    "Fetched %s (%s): trading_date=%s currency=%s current_price=%s "
                    "sma_50=%s sma_200=%s momentum=%s",
                    row.ticker,
                    row.company,
                    row.trading_date,
                    row.currency,
                    row.current_price,
                    row.sma_50,
                    row.sma_200,
                    row.momentum,
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

    if week_starts:
        try:
            upsert_market_for_weeks(database_url, week_starts)
        except Exception:
            logger.exception("Failed to upsert market stats")
            return 1

    try:
        metrics_purged, market_metrics_purged, indices_purged = (
            _run_retention_purge(database_url, retention_days)
        )
    except Exception:
        logger.exception("Retention purge failed")
        return 1

    try:
        _run_sector_trends(database_url, week_starts)
    except Exception:
        logger.exception("Failed to compute sector trends")
        return 1

    outliers_new = outliers_continuing = 0
    if week_starts:
        try:
            _run_indices(config, week_starts)
        except Exception:
            logger.exception("Failed to compute indices")
            return 1
        outliers_new, outliers_continuing = _run_outlier_email(config, week_starts)

    logger.info(
        "Summary: total=%d skipped=%d fetched=%d inserted=%d "
        "purged_metrics=%d purged_market_metrics=%d purged_indices=%d "
        "outliers_new=%d outliers_continuing=%d "
        "failed_batches=%d http_batches=%d",
        len(all_tickers),
        skipped_count,
        fetched_count,
        inserted_count,
        metrics_purged,
        market_metrics_purged,
        indices_purged,
        outliers_new,
        outliers_continuing,
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
