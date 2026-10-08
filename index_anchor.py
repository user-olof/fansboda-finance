"""Index daily series from member stocks' daily returns (specs/001-index-initial-sma,
specs/002-index-true-sma).

Pure logic: sector keys, daily stock returns folded into per-index averages,
the index's daily level series pinned at one known point (price 100 on its
start date, or its latest stored row), weekly price / SMA-50 / SMA-200 read
from that series, and the start-date rule (at least ``min_components`` members
with a close). ``compute_index_series`` is the one I/O wrapper (batched
yfinance download); no SQL.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from config import (
    DEFAULT_INDEX_HISTORY_TRADING_DAYS,
    DEFAULT_INDEX_MIN_COMPONENTS,
    DEFAULT_INDEX_START_DATE,
    DEFAULT_OUTLIER_MAX_GROWTH,
    DEFAULT_OUTLIER_MIN_GROWTH,
    DEFAULT_YF_BATCH_DELAY_SECONDS,
    DEFAULT_YF_BATCH_SIZE,
    DEFAULT_YF_MAX_RETRIES,
    DEFAULT_YF_RETRY_BASE_SECONDS,
    BaseConfig,
)
from db.country import CountrySet
from equity_index import (
    BASE_INDEX_PRICE,
    INDEX_DEFINITIONS,
    IndexLevels,
    WeekLevels,
    sector_index_definition,
)
from models import TickerEntry, week_start_of
from yfinance_client import download_batch

logger = logging.getLogger(__name__)

# Calendar days downloaded before a start date: covers 250 trading days plus
# holidays, so any later start date also has a full window in the same download.
DOWNLOAD_LOOKBACK_DAYS = 400
SMA_50_DAYS = 50
SMA_200_DAYS = 200


@dataclass(frozen=True)
class AnchorSettings:
    start_date: date = DEFAULT_INDEX_START_DATE
    trading_days: int = DEFAULT_INDEX_HISTORY_TRADING_DAYS
    min_components: int = DEFAULT_INDEX_MIN_COMPONENTS
    max_growth: float = DEFAULT_OUTLIER_MAX_GROWTH
    min_growth: float = DEFAULT_OUTLIER_MIN_GROWTH
    batch_size: int = DEFAULT_YF_BATCH_SIZE
    batch_delay_seconds: float = DEFAULT_YF_BATCH_DELAY_SECONDS
    max_retries: int = DEFAULT_YF_MAX_RETRIES
    retry_base_seconds: float = DEFAULT_YF_RETRY_BASE_SECONDS

    @classmethod
    def from_config(cls, config: BaseConfig) -> AnchorSettings:
        return cls(
            start_date=config.index_start_date,
            trading_days=config.index_history_trading_days,
            min_components=config.index_min_components,
            max_growth=config.outlier_max_growth,
            min_growth=config.outlier_min_growth,
            batch_size=config.yf_batch_size,
            batch_delay_seconds=config.yf_batch_delay_seconds,
            max_retries=config.yf_max_retries,
            retry_base_seconds=config.yf_retry_base_seconds,
        )


@dataclass(frozen=True)
class IndexSeries:
    """An index's daily levels, pinned at 100 on its start date."""

    ticker: str
    start_date: date
    levels: dict[date, float]


@dataclass
class SeriesResult:
    series: dict[str, IndexSeries] = field(default_factory=dict)
    below_minimum: set[str] = field(default_factory=set)
    missing_symbols: list[str] = field(default_factory=list)
    dropped_returns: int = 0


def sector_key(raw: str | None) -> str | None:
    """Python twin of ``SECTOR_KEY_SQL``: trim, spaces → ``-``, lower; blank → None."""
    if raw is None:
        return None
    key = raw.strip().replace(" ", "-").lower()
    return key or None


def index_tickers_for(entry: TickerEntry, country: CountrySet) -> list[str]:
    """The market index and (when the stock has a sector) its sector index."""
    tickers = [INDEX_DEFINITIONS[country].ticker]
    key = sector_key(entry.sector)
    if key is not None:
        tickers.append(sector_index_definition(country, key).ticker)
    return tickers


def missing_sector_indices(
    entries: Iterable[TickerEntry],
    stored_index_tickers: set[str],
    country: CountrySet,
    *,
    min_components: int = 1,
) -> dict[str, list[TickerEntry]]:
    """Sector index tickers with no stored rows, mapped to their member stocks.

    Sectors with fewer than ``min_components`` stocks in total can never reach
    the start-date minimum and are left out.
    """
    members: dict[str, list[TickerEntry]] = defaultdict(list)
    for entry in entries:
        key = sector_key(entry.sector)
        if key is None:
            continue
        ticker = sector_index_definition(country, key).ticker
        if ticker not in stored_index_tickers:
            members[ticker].append(entry)
    return {
        ticker: stocks
        for ticker, stocks in sorted(members.items())
        if len(stocks) >= min_components
    }


def _bar_dates(close: pd.Series) -> list[date]:
    return [pd.Timestamp(ts).date() for ts in close.index]


def _returns(
    close: pd.Series,
    *,
    max_growth: float,
    min_growth: float,
    until: date | None = None,
    after: date | None = None,
) -> tuple[dict[date, float], int]:
    """Daily returns on the stock's own consecutive bars, and the count dropped
    as outliers (above ``max_growth`` or below ``min_growth``)."""
    values = close.dropna()
    returns: dict[date, float] = {}
    dropped = 0
    previous: float | None = None
    for day, value in zip(_bar_dates(values), values.to_numpy(dtype=float)):
        if until is not None and day > until:
            break
        if previous is not None and previous > 0 and (after is None or day > after):
            change = value / previous - 1
            if min_growth <= change <= max_growth:
                returns[day] = change
            else:
                dropped += 1
        previous = value
    return returns, dropped


def daily_returns(
    close: pd.Series,
    *,
    end_date: date,
    max_growth: float,
    min_growth: float,
) -> dict[date, float]:
    """Daily close-to-close returns of one stock up to ``end_date``."""
    returns, _ = _returns(
        close, max_growth=max_growth, min_growth=min_growth, until=end_date
    )
    return returns


class DailyAccumulator:
    """Per index ticker: date → sum and count of member returns."""

    def __init__(self) -> None:
        self._sums: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
        self._counts: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))

    def add(self, index_tickers: Iterable[str], returns: dict[date, float]) -> None:
        for ticker in index_tickers:
            sums, counts = self._sums[ticker], self._counts[ticker]
            for day, change in returns.items():
                sums[day] += change
                counts[day] += 1

    def averages(self, ticker: str) -> dict[date, float]:
        counts = self._counts.get(ticker, {})
        return {
            day: total / counts[day]
            for day, total in self._sums.get(ticker, {}).items()
            if counts[day]
        }


def fold_close(
    accumulator: DailyAccumulator,
    index_tickers: Iterable[str],
    close: pd.Series,
    *,
    max_growth: float,
    min_growth: float,
    until: date | None = None,
    after: date | None = None,
) -> int:
    """Add one stock's daily returns (``≤ until`` / ``> after``) to its indices;
    returns the number of daily returns dropped as outliers."""
    returns, dropped = _returns(
        close, max_growth=max_growth, min_growth=min_growth, until=until, after=after
    )
    accumulator.add(index_tickers, returns)
    return dropped


def daily_levels(
    averages: dict[date, float], pin_date: date, pin_level: float
) -> dict[date, float]:
    """The index's daily levels with ``level(pin_date) = pin_level``.

    Later levels are multiplied forward by one plus the day's average return,
    earlier ones divided backward by it. A pin date without an average return
    is part of the series with no change on that day.
    """
    days = sorted(set(averages) | {pin_date})
    pin = days.index(pin_date)
    levels = {pin_date: pin_level}
    level = pin_level
    for day in days[pin + 1 :]:
        level *= 1 + averages[day]
        levels[day] = level
    level = pin_level
    for i in range(pin, 0, -1):
        level /= 1 + averages.get(days[i], 0.0)
        levels[days[i - 1]] = level
    return levels


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


def week_levels(
    levels: dict[date, float], week_start: date, *, row_date: date | None = None
) -> WeekLevels | None:
    """Price and SMA-50 / SMA-200 of the week's row.

    The row date is the last series date in the week (``row_date`` when given,
    e.g. the start date on the start week). SMAs are the means of the last 50 /
    200 levels up to and including it (fewer when not available).
    """
    week_end = week_start + timedelta(days=7)
    if row_date is not None:
        if row_date not in levels or not week_start <= row_date < week_end:
            return None
        day = row_date
    else:
        in_week = [d for d in levels if week_start <= d < week_end]
        if not in_week:
            return None
        day = max(in_week)
    history = [levels[d] for d in sorted(d for d in levels if d <= day)]
    last_50 = history[-SMA_50_DAYS:]
    last_200 = history[-SMA_200_DAYS:]
    return WeekLevels(
        trading_date=day,
        levels=IndexLevels(
            current_price=_to_decimal(levels[day]),
            sma_50=_to_decimal(sum(last_50) / len(last_50)),
            sma_200=_to_decimal(sum(last_200) / len(last_200)),
        ),
        days_used=len(last_200),
    )


def series_week_levels(
    series: Iterable[IndexSeries], weeks: Iterable[date]
) -> dict[date, dict[str, WeekLevels]]:
    """Week → index ticker → levels, for every week from each index's start week."""
    result: dict[date, dict[str, WeekLevels]] = defaultdict(dict)
    week_list = sorted(set(weeks))
    for index in series:
        start_week = week_start_of(index.start_date)
        for week in week_list:
            if week < start_week:
                continue
            row = week_levels(
                index.levels,
                week,
                row_date=index.start_date if week == start_week else None,
            )
            if row is not None:
                result[week][index.ticker] = row
    return dict(result)


def candidate_dates(trading_dates: Iterable[date], start_date: date) -> list[date]:
    """The start date, then the last trading date of each later calendar week."""
    start_week = week_start_of(start_date)
    last_by_week: dict[date, date] = {}
    for day in trading_dates:
        week = week_start_of(day)
        if week > start_week and (week not in last_by_week or day > last_by_week[week]):
            last_by_week[week] = day
    return [start_date, *sorted(last_by_week.values())]


def find_start_date(
    counts: dict[date, int], candidates: list[date], min_components: int
) -> date | None:
    """First candidate date on which at least ``min_components`` members have a close."""
    for candidate in candidates:
        if counts.get(candidate, 0) >= min_components:
            return candidate
    return None


def closes_from_download(data: pd.DataFrame, batch: list[str]) -> dict[str, pd.Series]:
    """Non-empty ``Close`` series per ticker from a batch download."""
    closes: dict[str, pd.Series] = {}
    if data.empty:
        return closes
    if isinstance(data.columns, pd.MultiIndex):
        available = set(data.columns.get_level_values(0))
        for symbol in batch:
            if symbol in available and "Close" in data[symbol].columns:
                close = data[symbol]["Close"].dropna()
                if not close.empty:
                    closes[symbol] = close
    elif len(batch) == 1 and "Close" in data.columns:
        close = data["Close"].dropna()
        if not close.empty:
            closes[batch[0]] = close
    return closes


@dataclass
class _Scan:
    daily: DailyAccumulator = field(default_factory=DailyAccumulator)
    counts: dict[str, dict[date, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    trading_dates: set[date] = field(default_factory=set)
    missing_symbols: list[str] = field(default_factory=list)
    dropped: int = 0


def _scan(
    entries: list[TickerEntry],
    country: CountrySet,
    settings: AnchorSettings,
    *,
    start_date: date,
    scope: set[str] | None,
) -> _Scan:
    """Download the members once (to today) and fold each batch into per-index sums.

    Returns up to the start date come only from members with a close on it;
    later returns from every member with data.
    """
    from fetch_sma import chunked

    scan = _Scan()
    by_symbol = {entry.symbol: entry for entry in entries}
    batches = chunked(list(by_symbol), settings.batch_size)
    bounds = {"max_growth": settings.max_growth, "min_growth": settings.min_growth}
    for i, batch in enumerate(batches):
        logger.info(
            "Index history batch %d/%d (%d tickers, start date %s)",
            i + 1,
            len(batches),
            len(batch),
            start_date.isoformat(),
        )
        try:
            data = download_batch(
                batch,
                start_date - timedelta(days=DOWNLOAD_LOOKBACK_DAYS),
                max_retries=settings.max_retries,
                retry_base_seconds=settings.retry_base_seconds,
            )
            closes = closes_from_download(data, batch)
        except Exception:
            logger.exception("Failed index history batch %d/%d", i + 1, len(batches))
            closes = {}
        for symbol in batch:
            close = closes.get(symbol)
            if close is None:
                scan.missing_symbols.append(symbol)
                continue
            tickers = [
                ticker
                for ticker in index_tickers_for(by_symbol[symbol], country)
                if scope is None or ticker in scope
            ]
            days = _bar_dates(close)
            for day in days:
                if day >= start_date:
                    scan.trading_dates.add(day)
                    for ticker in tickers:
                        scan.counts[ticker][day] += 1
            if start_date in days:
                scan.dropped += fold_close(
                    scan.daily, tickers, close, until=start_date, **bounds
                )
            scan.dropped += fold_close(
                scan.daily, tickers, close, after=start_date, **bounds
            )
        if i < len(batches) - 1:
            time.sleep(settings.batch_delay_seconds)
    return scan


def _series(
    ticker: str, scan: _Scan, start_date: date, trading_days: int
) -> IndexSeries | None:
    """Series pinned at 100 on the start date, from the last ``trading_days``
    return dates up to it and every later one."""
    averages = scan.daily.averages(ticker)
    if not averages:
        return None
    kept = set(sorted(day for day in averages if day <= start_date)[-trading_days:])
    averages = {
        day: value for day, value in averages.items() if day > start_date or day in kept
    }
    return IndexSeries(
        ticker, start_date, daily_levels(averages, start_date, float(BASE_INDEX_PRICE))
    )


def compute_index_series(
    entries: list[TickerEntry],
    country: CountrySet,
    *,
    settings: AnchorSettings,
    index_tickers: set[str] | None = None,
) -> SeriesResult:
    """Daily series for the country's market and sector indices (or ``index_tickers``).

    An index starts on ``settings.start_date`` when at least
    ``settings.min_components`` members have a close on it; otherwise on the
    first later week's last trading date that reaches the minimum, computed by
    a second download of just those indices' members.
    """
    result = SeriesResult()
    scope = index_tickers
    scan = _scan(entries, country, settings, start_date=settings.start_date, scope=scope)
    result.missing_symbols = scan.missing_symbols
    result.dropped_returns = scan.dropped
    if scan.missing_symbols:
        logger.warning(
            "%s: no daily history for %d stock(s): %s",
            country.value,
            len(scan.missing_symbols),
            ", ".join(scan.missing_symbols[:20]),
        )

    tickers = {
        ticker
        for entry in entries
        for ticker in index_tickers_for(entry, country)
        if scope is None or ticker in scope
    }
    candidates = candidate_dates(scan.trading_dates, settings.start_date)
    later: dict[date, set[str]] = defaultdict(set)
    for ticker in sorted(tickers):
        counts = scan.counts.get(ticker, {})
        if counts.get(settings.start_date, 0) >= settings.min_components:
            index = _series(ticker, scan, settings.start_date, settings.trading_days)
            if index is not None:
                result.series[ticker] = index
            continue
        start = find_start_date(counts, candidates, settings.min_components)
        if start is None:
            result.below_minimum.add(ticker)
            logger.warning(
                "Index %s: never %d member stocks with a close on the same week-end; "
                "not started",
                ticker,
                settings.min_components,
            )
        else:
            later[start].add(ticker)

    for start, group in sorted(later.items()):
        members = [
            entry
            for entry in entries
            if any(ticker in group for ticker in index_tickers_for(entry, country))
        ]
        logger.info(
            "Index(es) %s: fewer than %d members on %s; start date %s",
            ", ".join(sorted(group)),
            settings.min_components,
            settings.start_date.isoformat(),
            start.isoformat(),
        )
        second = _scan(members, country, settings, start_date=start, scope=group)
        result.dropped_returns += second.dropped
        for ticker in sorted(group):
            index = _series(ticker, second, start, settings.trading_days)
            if index is not None:
                result.series[ticker] = index
    return result
