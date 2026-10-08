"""Index start levels from reconstructed daily history (specs/001-index-initial-sma).

Pure logic: sector keys, daily stock returns, the index's daily level worked
backwards from 100 on its start date, initial SMA-50 / SMA-200 as averages of
those levels, the start-date rule (at least ``min_components`` members with a
close), and the weekly bridge over weeks no longer stored. ``compute_anchors``
is the one I/O wrapper (batched yfinance download); no SQL.
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
    sector_index_definition,
)
from models import MetricRow, TickerEntry, week_start_of
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
class Anchor:
    """Levels an index chains from when it has no stored row.

    ``week_start`` is the index's start week (base row, price 100) or, when the
    weeks after the start date are no longer stored, the week before the oldest
    stored week (levels bridged from the start date).
    """

    ticker: str
    start_date: date
    week_start: date
    trading_date: date
    levels: IndexLevels
    days_used: int


@dataclass
class AnchorResult:
    anchors: dict[str, Anchor] = field(default_factory=dict)
    below_minimum: set[str] = field(default_factory=set)
    missing_symbols: list[str] = field(default_factory=list)


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


def daily_returns(
    close: pd.Series,
    *,
    end_date: date,
    max_growth: float,
    min_growth: float,
) -> dict[date, float]:
    """Daily close-to-close returns of one stock up to ``end_date``.

    Returns use the stock's own consecutive bars; a return above ``max_growth``
    or below ``min_growth`` is dropped (same limits as the weekly outlier rule).
    """
    values = close.dropna()
    returns: dict[date, float] = {}
    previous: float | None = None
    for day, value in zip(_bar_dates(values), values.to_numpy(dtype=float)):
        if day > end_date:
            break
        if previous is not None and previous > 0:
            change = value / previous - 1
            if min_growth <= change <= max_growth:
                returns[day] = change
        previous = value
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


def reconstruct_levels(
    averages: dict[date, float], start_date: date, trading_days: int
) -> list[float]:
    """Daily index levels, oldest first, ending with 100 on ``start_date``.

    Uses the last ``trading_days`` dates with an average return up to the start
    date: the level before a day equals that day's level / (1 + its average).
    """
    days = sorted(day for day in averages if day <= start_date)[-trading_days:]
    level = float(BASE_INDEX_PRICE)
    levels = [level]
    for day in reversed(days):
        level /= 1 + averages[day]
        levels.append(level)
    levels.reverse()
    return levels


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


def initial_smas(levels: list[float]) -> tuple[Decimal, Decimal, int]:
    """Mean of the last 50 and last 200 levels (fewer when not available)."""
    last_50 = levels[-SMA_50_DAYS:]
    last_200 = levels[-SMA_200_DAYS:]
    return (
        _to_decimal(sum(last_50) / len(last_50)),
        _to_decimal(sum(last_200) / len(last_200)),
        len(last_200),
    )


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


def _eligible_growth(
    row: MetricRow, *, max_growth: float, min_growth: float
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Same filter as ``CHAINED_WEEK_STATS_SQL``: positive levels, all growth in bounds."""
    if not (
        row.current_price is not None
        and row.sma_50 is not None
        and row.sma_200 is not None
        and row.current_price > 0
        and row.sma_50 > 0
        and row.sma_200 > 0
    ):
        return None
    growths = (row.price_growth, row.sma_50_growth, row.sma_200_growth)
    if any(g is None or not min_growth <= float(g) <= max_growth for g in growths):
        return None
    return growths  # type: ignore[return-value]


class WeeklyAccumulator:
    """Per index ticker and week: count, growth sums, and latest trading date."""

    def __init__(self) -> None:
        self._weeks: dict[str, dict[date, list]] = defaultdict(dict)

    def add(
        self,
        index_tickers: Iterable[str],
        rows: Iterable[MetricRow],
        *,
        max_growth: float,
        min_growth: float,
    ) -> None:
        tickers = list(index_tickers)
        for row in rows:
            growth = _eligible_growth(row, max_growth=max_growth, min_growth=min_growth)
            if growth is None:
                continue
            for ticker in tickers:
                stats = self._weeks[ticker].setdefault(
                    row.week_start, [0, Decimal(0), Decimal(0), Decimal(0), row.trading_date]
                )
                stats[0] += 1
                for i, value in enumerate(growth, start=1):
                    stats[i] += value
                stats[4] = max(stats[4], row.trading_date)

    def chain(
        self, ticker: str, levels: IndexLevels, weeks: Iterable[date]
    ) -> tuple[IndexLevels, date | None]:
        """Chain ``levels`` through ``weeks`` by the mean growth; empty weeks carry over."""
        last_date: date | None = None
        one = Decimal(1)
        for week in sorted(weeks):
            stats = self._weeks.get(ticker, {}).get(week)
            if not stats:
                continue
            count, g_price, g_sma_50, g_sma_200, trading_date = stats
            levels = IndexLevels(
                current_price=levels.current_price * (one + g_price / count),
                sma_50=levels.sma_50 * (one + g_sma_50 / count),
                sma_200=levels.sma_200 * (one + g_sma_200 / count),
            )
            last_date = trading_date
        return levels, last_date


def _bridge_weeks(start_date: date, first_stored_week: date | None) -> list[date]:
    """Calendar weeks after the start week and before the oldest stored week."""
    if first_stored_week is None:
        return []
    weeks = []
    week = week_start_of(start_date) + timedelta(days=7)
    while week < first_stored_week:
        weeks.append(week)
        week += timedelta(days=7)
    return weeks


def build_anchor(
    ticker: str,
    averages: dict[date, float],
    weekly: WeeklyAccumulator,
    *,
    start_date: date,
    trading_days: int,
    first_stored_week: date | None,
) -> Anchor | None:
    """Initial levels on ``start_date``, bridged to the week before the oldest stored week."""
    if not averages:
        return None
    sma_50, sma_200, days_used = initial_smas(
        reconstruct_levels(averages, start_date, trading_days)
    )
    levels = IndexLevels(BASE_INDEX_PRICE, sma_50, sma_200)
    week_start, trading_date = week_start_of(start_date), start_date
    bridge = _bridge_weeks(start_date, first_stored_week)
    if bridge:
        levels, last_date = weekly.chain(ticker, levels, bridge)
        week_start = bridge[-1]
        trading_date = last_date or start_date
    return Anchor(ticker, start_date, week_start, trading_date, levels, days_used)


def _closes(data: pd.DataFrame, batch: list[str]) -> dict[str, pd.Series]:
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
    weekly: WeeklyAccumulator = field(default_factory=WeeklyAccumulator)
    counts: dict[str, dict[date, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    trading_dates: set[date] = field(default_factory=set)
    missing_symbols: list[str] = field(default_factory=list)


def _scan(
    entries: list[TickerEntry],
    country: CountrySet,
    settings: AnchorSettings,
    *,
    start_date: date,
    first_stored_week: date | None,
    scope: set[str] | None,
) -> _Scan:
    """Download the members once and fold each batch into per-index sums."""
    from backfill_sma import metric_rows_from_weekly_samples
    from fetch_sma import chunked

    scan = _Scan()
    by_symbol = {entry.symbol: entry for entry in entries}
    bridge = _bridge_weeks(start_date, first_stored_week)
    start_week = week_start_of(start_date)
    batches = chunked(list(by_symbol), settings.batch_size)
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
            closes = _closes(data, batch)
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
                scan.daily.add(
                    tickers,
                    daily_returns(
                        close,
                        end_date=start_date,
                        max_growth=settings.max_growth,
                        min_growth=settings.min_growth,
                    ),
                )
            if bridge:
                bridge_end = pd.Timestamp(bridge[-1] + timedelta(days=7))
                history = pd.DataFrame({"Close": close[close.index < bridge_end]})
                rows = [
                    row
                    for row in metric_rows_from_weekly_samples(symbol, history, company=None)
                    if row.week_start > start_week
                ]
                scan.weekly.add(
                    tickers,
                    rows,
                    max_growth=settings.max_growth,
                    min_growth=settings.min_growth,
                )
        if i < len(batches) - 1:
            time.sleep(settings.batch_delay_seconds)
    return scan


def compute_anchors(
    entries: list[TickerEntry],
    country: CountrySet,
    *,
    settings: AnchorSettings,
    first_stored_week: date | None = None,
    index_tickers: set[str] | None = None,
) -> AnchorResult:
    """Anchors for the country's market and sector indices (or ``index_tickers``).

    An index starts on ``settings.start_date`` when at least
    ``settings.min_components`` members have a close on it; otherwise on the
    first later week's last trading date that reaches the minimum, computed by
    a second download of just those indices' members. Members are the stocks
    with a close on the index's start date. When ``first_stored_week`` is after
    the start week, the levels are bridged to the week before it.
    """
    result = AnchorResult()
    scope = index_tickers
    scan = _scan(
        entries,
        country,
        settings,
        start_date=settings.start_date,
        first_stored_week=first_stored_week,
        scope=scope,
    )
    result.missing_symbols = scan.missing_symbols
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
            anchor = build_anchor(
                ticker,
                scan.daily.averages(ticker),
                scan.weekly,
                start_date=settings.start_date,
                trading_days=settings.trading_days,
                first_stored_week=first_stored_week,
            )
            if anchor is not None:
                result.anchors[ticker] = anchor
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
        second = _scan(
            members,
            country,
            settings,
            start_date=start,
            first_stored_week=first_stored_week,
            scope=group,
        )
        for ticker in sorted(group):
            anchor = build_anchor(
                ticker,
                second.daily.averages(ticker),
                second.weekly,
                start_date=start,
                trading_days=settings.trading_days,
                first_stored_week=first_stored_week,
            )
            if anchor is not None:
                result.anchors[ticker] = anchor
    return result
