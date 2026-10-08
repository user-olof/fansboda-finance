"""Tests for PRD §5.8 equal-weighted market and sector indices (RFC-015 / 016 / 017 / 018,
specs/002-index-true-sma)."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest

from compute_indices import build_parser, initialize_indices, main
from config import BaseConfig
from db.country import CountrySet
from db.indices import (
    BASE_WEEK_STATS_SQL,
    DELETE_COUNTRY_INDICES_SQL,
    DELETE_COUNTRY_WEEK_SQL,
    DELETE_STALE_INDICES_SQL,
    INSERT_INDEX_SQL,
    LOAD_COUNTRY_INDEX_TICKERS_SQL,
    LOAD_COUNTRY_WEEK_INDICES_SQL,
    LOAD_PREVIOUS_INDICES_SQL,
    IndexWriteResult,
    load_index_tickers,
    load_previous_indices,
    purge_stale_indices,
    write_index_weeks,
)
from equity_index import (
    COUNTRY_CURRENCY,
    INDEX_DEFINITIONS,
    IndexLevels,
    IndexRow,
    WeekLevels,
    build_index_row,
    index_momentum,
    is_outlier,
    sector_index_definition,
    with_sector_z_scores,
)
from index_anchor import AnchorSettings, IndexSeries, SeriesResult
from models import OutlierRow, TickerEntry

US = INDEX_DEFINITIONS[CountrySet.US]
W1 = date(2026, 6, 1)
W2 = date(2026, 6, 8)
W3 = date(2026, 6, 15)
D1 = date(2026, 6, 5)
D2 = date(2026, 6, 12)
LEVELS = IndexLevels(Decimal("100"), Decimal("95"), Decimal("90"))


def _week(day: date, levels: IndexLevels = LEVELS) -> WeekLevels:
    return WeekLevels(day, levels, 200)


def _mock_config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {"database_url": "postgresql://example"}
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


def _mock_conn(fetchall: list[object] | None = None) -> tuple[MagicMock, MagicMock]:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = fetchall or []
    mock_cursor.rowcount = 0
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn, mock_cursor


def test_index_definitions_match_prd() -> None:
    assert {(d.ticker, d.name) for d in INDEX_DEFINITIONS.values()} == {
        ("US-IDX", "NYSE & Nasdaq"),
        ("SWE-IDX", "OMX Stockholm"),
        ("UK-IDX", "FTSE London"),
    }
    for country, definition in INDEX_DEFINITIONS.items():
        assert definition.country is country


YFINANCE_SECTOR_KEYS = (
    "basic-materials",
    "communication-services",
    "consumer-cyclical",
    "consumer-defensive",
    "energy",
    "financial-services",
    "healthcare",
    "industrials",
    "real-estate",
    "technology",
    "utilities",
)


def test_market_labels_do_not_collide_with_sector_labels() -> None:
    market_names = {d.name for d in INDEX_DEFINITIONS.values()}
    assert len(market_names) == len(INDEX_DEFINITIONS)
    for country in INDEX_DEFINITIONS:
        for key in YFINANCE_SECTOR_KEYS:
            assert sector_index_definition(country, key).name not in market_names


def test_index_momentum() -> None:
    assert index_momentum(Decimal("110"), Decimal("100")) == Decimal("1.1")
    assert index_momentum(Decimal("110"), Decimal("0")) is None


def test_build_index_row_uses_series_levels() -> None:
    levels = IndexLevels(Decimal("104.5"), Decimal("95"), Decimal("90"))
    row = build_index_row(US, trading_date=D1, ticker_count=4, levels=levels)
    assert row is not None
    assert (row.trading_date, row.ticker_count) == (D1, 4)
    assert row.levels == levels
    assert row.momentum == Decimal("95") / Decimal("90")
    assert (row.ticker, row.sector, row.country) == (
        "US-IDX",
        "NYSE & Nasdaq",
        CountrySet.US,
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trading_date": D1, "ticker_count": 0},
        {"trading_date": None, "ticker_count": 2},
    ],
)
def test_build_index_row_skips_week_without_contributors(kwargs: dict) -> None:
    assert build_index_row(US, levels=LEVELS, **kwargs) is None


@pytest.mark.parametrize("country", list(CountrySet))
def test_index_sql_targets_country_metrics(country: CountrySet) -> None:
    prefix = country.value
    sector_key = "NULLIF(lower(replace(btrim(t.sector), ' ', '-')), '') AS sector"
    base = " ".join(BASE_WEEK_STATS_SQL[country].split())
    assert f"FROM {prefix}_metrics m JOIN {prefix}_tickers t ON t.symbol = m.ticker" in base
    assert sector_key in base
    assert "growth" not in base
    assert "m.current_price > 0 AND m.sma_50 > 0 AND m.sma_200 > 0" in base
    assert "GROUP BY GROUPING SETS ((), (sector))" in base
    assert "100.0 * AVG(CASE WHEN sma_50 > sma_200 THEN 1 ELSE 0 END)" in base
    assert base.count("%s") == 1


def test_static_index_sql_is_parameterized() -> None:
    assert INSERT_INDEX_SQL.count("%s") == 12
    for column in ("sector", "currency", "pct_uptrend", "z_score"):
        assert column in INSERT_INDEX_SQL
    assert "name" not in INSERT_INDEX_SQL
    load = " ".join(LOAD_PREVIOUS_INDICES_SQL.split())
    assert "SELECT DISTINCT ON (ticker) ticker, trading_date, current_price" in load
    assert "WHERE country = %s AND trading_date < %s" in load
    assert " ".join(DELETE_COUNTRY_WEEK_SQL.split()) == (
        "DELETE FROM indices WHERE country = %s AND trading_date >= %s "
        "AND trading_date < %s"
    )
    assert DELETE_COUNTRY_INDICES_SQL == "DELETE FROM indices WHERE country = %s"
    assert DELETE_STALE_INDICES_SQL == "DELETE FROM indices WHERE trading_date < %s"
    assert LOAD_COUNTRY_INDEX_TICKERS_SQL == (
        "SELECT DISTINCT ticker FROM indices WHERE country = %s"
    )
    week = " ".join(LOAD_COUNTRY_WEEK_INDICES_SQL.split())
    assert "WHERE country = %s AND trading_date >= %s AND trading_date < %s" in week
    assert week.count("%s") == 3


def _inserted(mock_cursor: MagicMock) -> list[tuple]:
    return [
        c.args[1]
        for c in mock_cursor.execute.call_args_list
        if c.args[0] == INSERT_INDEX_SQL
    ]


def test_write_index_weeks_writes_series_levels_with_stats() -> None:
    later = IndexLevels(Decimal("104.5"), Decimal("101"), Decimal("98"))
    mock_conn, mock_cursor = _mock_conn(
        fetchall=[
            [(1, None, 3, D1, Decimal("66.7"))],
            [(1, None, 2, D2, Decimal("50"))],
        ]
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        result = write_index_weeks(
            "postgresql://example",
            {W2: {"US-IDX": _week(D2, later)}, W1: {"US-IDX": _week(D1)}},
            country=CountrySet.US,
            rebuild=True,
        )

    assert [(r.trading_date, r.ticker_count, r.levels) for r in result.rows] == [
        (D1, 3, LEVELS),
        (D2, 2, later),
    ]
    executed = mock_cursor.execute.call_args_list
    assert executed[0] == call(DELETE_COUNTRY_INDICES_SQL, ("us",))
    assert executed[1] == call(BASE_WEEK_STATS_SQL[CountrySet.US], (W1,))
    assert executed[2] == call(DELETE_COUNTRY_WEEK_SQL, ("us", W1, W2))
    assert executed[3] == call(
        INSERT_INDEX_SQL,
        (
            "US-IDX",
            "NYSE & Nasdaq",
            "us",
            "USD",
            D1,
            3,
            Decimal("100"),
            Decimal("95"),
            Decimal("90"),
            Decimal("66.7"),
            Decimal("95") / Decimal("90"),
            None,
        ),
    )
    assert executed[4] == call(BASE_WEEK_STATS_SQL[CountrySet.US], (W2,))
    assert executed[5] == call(DELETE_COUNTRY_WEEK_SQL, ("us", W2, W3))
    assert _inserted(mock_cursor)[1][9] == Decimal("50")
    mock_conn.commit.assert_called_once()


def test_write_index_weeks_sector_rows_with_z_scores() -> None:
    stats = [
        (1, None, 3, D2, Decimal("50")),
        (0, "energy", 1, D2, Decimal("0")),
        (0, "technology", 2, D2, Decimal("100")),
        (0, None, 0, D2, Decimal("0")),  # blank sector
    ]
    mock_conn, mock_cursor = _mock_conn(fetchall=[stats])
    levels = {
        "US-IDX": _week(D2),
        "US-IDX-ENERGY": _week(D2, IndexLevels(Decimal("99"), Decimal("90"), Decimal("100"))),
        "US-IDX-TECHNOLOGY": _week(
            D2, IndexLevels(Decimal("110"), Decimal("120"), Decimal("100"))
        ),
        "US-IDX-UTILITIES": _week(D2),  # no stocks this week
    }

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        rows = write_index_weeks(
            "postgresql://example", {W2: levels}, country=CountrySet.US
        ).rows

    by_ticker = {row.ticker: row for row in rows}
    assert list(by_ticker) == ["US-IDX", "US-IDX-ENERGY", "US-IDX-TECHNOLOGY"]
    market = by_ticker["US-IDX"]
    assert (market.sector, market.sector_key, market.currency, market.z_score) == (
        "NYSE & Nasdaq",
        None,
        "USD",
        None,
    )
    energy = by_ticker["US-IDX-ENERGY"]
    assert (energy.sector, energy.sector_key, energy.ticker_count) == ("Energy", "energy", 1)
    tech = by_ticker["US-IDX-TECHNOLOGY"]
    assert tech.pct_uptrend == Decimal("100")
    # Two sectors with momentum 0.9 and 1.2: z = ±1 (population std).
    assert energy.z_score == Decimal("-1")
    assert tech.z_score == Decimal("1")
    assert len(_inserted(mock_cursor)) == 3


def test_write_index_weeks_removes_week_without_contributors() -> None:
    mock_conn, mock_cursor = _mock_conn(fetchall=[[(1, None, 0, None, None)]])

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        result = write_index_weeks(
            "postgresql://example", {W2: {"SWE-IDX": _week(D2)}}, country=CountrySet.SWE
        )

    assert result == IndexWriteResult(rows=[])
    sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
    assert INSERT_INDEX_SQL not in sqls
    assert DELETE_COUNTRY_INDICES_SQL not in sqls
    assert mock_cursor.execute.call_args_list[-1] == call(
        DELETE_COUNTRY_WEEK_SQL, ("swe", W2, W3)
    )


def test_write_index_weeks_only_tickers_keeps_other_rows_and_updates_z_scores() -> None:
    stats = [
        (1, None, 3, D2, Decimal("50")),
        (0, "energy", 1, D2, Decimal("0")),
        (0, "technology", 2, D2, Decimal("100")),
    ]
    stored = [
        ("US-IDX", "NYSE & Nasdaq", "USD", D2, 3, Decimal("101"), Decimal("95"),
         Decimal("90"), Decimal("50"), Decimal("95") / Decimal("90")),
        ("US-IDX-TECHNOLOGY", "Technology", "USD", D2, 2, Decimal("105"),
         Decimal("120"), Decimal("100"), Decimal("100"), Decimal("1.2")),
        ("US-IDX-ENERGY", "Energy", "USD", D2, 1, Decimal("1"), Decimal("1"),
         Decimal("1"), Decimal("0"), Decimal("1")),
    ]
    mock_conn, mock_cursor = _mock_conn(fetchall=[stats, stored])
    energy = IndexLevels(Decimal("100"), Decimal("90"), Decimal("100"))

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        result = write_index_weeks(
            "postgresql://example",
            {W2: {"US-IDX": _week(D2), "US-IDX-ENERGY": _week(D2, energy)}},
            country=CountrySet.US,
            only_tickers={"US-IDX-ENERGY"},
        )

    assert [r.ticker for r in result.rows] == ["US-IDX-ENERGY"]
    assert mock_cursor.execute.call_args_list[1] == call(
        LOAD_COUNTRY_WEEK_INDICES_SQL, ("us", W2, W3)
    )
    inserted = {values[0]: values for values in _inserted(mock_cursor)}
    assert set(inserted) == {"US-IDX", "US-IDX-TECHNOLOGY", "US-IDX-ENERGY"}
    assert inserted["US-IDX"][6:9] == (Decimal("101"), Decimal("95"), Decimal("90"))
    assert inserted["US-IDX-TECHNOLOGY"][6] == Decimal("105")
    assert inserted["US-IDX-TECHNOLOGY"][11] == Decimal("1")
    assert inserted["US-IDX-ENERGY"][6:9] == (Decimal("100"), Decimal("90"), Decimal("100"))
    assert inserted["US-IDX-ENERGY"][11] == Decimal("-1")


def test_write_index_weeks_only_tickers_without_rows_leaves_week() -> None:
    mock_conn, mock_cursor = _mock_conn(fetchall=[[(1, None, 0, None, None)]])

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        result = write_index_weeks(
            "postgresql://example",
            {W2: {"US-IDX": _week(D2)}},
            country=CountrySet.US,
            only_tickers={"US-IDX"},
        )

    assert result.rows == []
    sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
    assert DELETE_COUNTRY_WEEK_SQL not in sqls


def test_load_previous_indices() -> None:
    mock_conn, mock_cursor = _mock_conn(
        fetchall=[[("US-IDX", D1, Decimal("105")), ("US-IDX-ENERGY", D1, Decimal("98"))]]
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        pins = load_previous_indices("postgresql://example", CountrySet.US, W2)

    assert pins == {
        "US-IDX": (D1, Decimal("105")),
        "US-IDX-ENERGY": (D1, Decimal("98")),
    }
    mock_cursor.execute.assert_called_once_with(LOAD_PREVIOUS_INDICES_SQL, ("us", W2))


def test_load_index_tickers() -> None:
    mock_conn, mock_cursor = _mock_conn(fetchall=[[("US-IDX",), ("US-IDX-ENERGY",)]])

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        assert load_index_tickers("postgresql://example", CountrySet.US) == {
            "US-IDX",
            "US-IDX-ENERGY",
        }

    mock_cursor.execute.assert_called_once_with(LOAD_COUNTRY_INDEX_TICKERS_SQL, ("us",))


def test_sector_index_definition() -> None:
    definition = sector_index_definition(CountrySet.SWE, "financial-services")
    assert definition.ticker == "SWE-IDX-FINANCIAL-SERVICES"
    assert definition.name == "Financial Services"
    assert sector_index_definition(CountrySet.US, "financial-services").name == (
        "Financial Services"
    )
    assert definition.sector_key == "financial-services"
    assert definition.currency == "SEK"
    assert COUNTRY_CURRENCY == {
        CountrySet.US: "USD",
        CountrySet.SWE: "SEK",
        CountrySet.UK: "GBP",
    }
    assert INDEX_DEFINITIONS[CountrySet.US].sector_key is None


def _sector_row(sector: str | None, momentum: Decimal | None) -> IndexRow:
    return IndexRow(
        "X", "X", CountrySet.US, D1, 1, Decimal("100"), Decimal("1"), Decimal("1"),
        momentum, sector_key=sector,
    )


def test_with_sector_z_scores_uses_population_std_over_sectors() -> None:
    rows = with_sector_z_scores(
        [
            _sector_row(None, Decimal("5")),
            _sector_row("a", Decimal("1")),
            _sector_row("b", Decimal("2")),
            _sector_row("c", Decimal("3")),
            _sector_row("d", None),
        ]
    )
    std = (Decimal(2) / Decimal(3)).sqrt()
    assert [r.z_score for r in rows] == [
        None,
        Decimal("-1") / std,
        Decimal("0"),
        Decimal("1") / std,
        None,
    ]


@pytest.mark.parametrize(
    "momenta",
    [
        [Decimal("1.1")],  # fewer than two sectors
        [Decimal("1.1"), Decimal("1.1")],  # zero std
    ],
)
def test_with_sector_z_scores_null_without_spread(momenta: list[Decimal]) -> None:
    rows = with_sector_z_scores([_sector_row(f"s{i}", m) for i, m in enumerate(momenta)])
    assert all(row.z_score is None for row in rows)


def test_purge_stale_indices_uses_retention_cutoff() -> None:
    mock_conn, mock_cursor = _mock_conn([])
    mock_cursor.rowcount = 4

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        with patch("db.indices.retention_cutoff", return_value=date(2025, 6, 2)):
            assert purge_stale_indices("postgresql://example", 365) == 4

    mock_cursor.execute.assert_called_once_with(
        DELETE_STALE_INDICES_SQL, (date(2025, 6, 2),)
    )

def _row(trading_date: date) -> IndexRow:
    return IndexRow(
        "US-IDX",
        "NYSE & Nasdaq",
        CountrySet.US,
        trading_date,
        2,
        Decimal("100"),
        Decimal("95"),
        Decimal("90"),
        Decimal("95") / Decimal("90"),
    )


SETTINGS = AnchorSettings(start_date=D1)


def _entry(symbol: str, sector: str | None = "Energy") -> TickerEntry:
    return TickerEntry(symbol, symbol, sector=sector)


@pytest.fixture(autouse=True)
def _stub_io():
    with patch("compute_indices.load_outliers", return_value=[]) as outliers, patch(
        "compute_indices.load_tickers_from_db", return_value=[_entry("A")]
    ), patch("compute_indices.load_index_tickers", return_value=set()) as stored:
        yield outliers, stored


def _levels(start: date = D1) -> dict[date, float]:
    """Flat at 100 from the start date through the next week."""
    days = [start + date.resolution * i for i in range(0, 10)]
    return {day: 100.0 for day in days if day.weekday() < 5}


def _result(
    *tickers: str, below: set[str] | None = None, start: date = D1
) -> SeriesResult:
    return SeriesResult(
        series={ticker: IndexSeries(ticker, start, _levels(start)) for ticker in tickers},
        below_minimum=below or set(),
    )


def test_initialize_indices_writes_every_week_from_series(caplog) -> None:
    result = _result("US-IDX", "US-IDX-ENERGY")
    with patch(
        "compute_indices.load_distinct_week_starts",
        return_value=[date(2026, 5, 25), W1, W2],
    ), patch("compute_indices.compute_index_series", return_value=result) as mock_series:
        with patch(
            "compute_indices.write_index_weeks",
            return_value=IndexWriteResult([_row(D1), _row(D2)]),
        ) as mock_write:
            with caplog.at_level("INFO", logger="compute_indices"):
                written, failed = initialize_indices(
                    "postgresql://example", country=CountrySet.US, settings=SETTINGS
                )

    assert (written, failed) == (2, [])
    mock_series.assert_called_once_with([_entry("A")], CountrySet.US, settings=SETTINGS)
    (url, levels), kwargs = mock_write.call_args
    assert kwargs == {"country": CountrySet.US, "rebuild": True}
    assert sorted(levels) == [W1, W2]
    start = levels[W1]["US-IDX"]
    assert start.trading_date == D1
    assert start.levels == IndexLevels(Decimal("100.0"), Decimal("100.0"), Decimal("100.0"))
    assert levels[W2]["US-IDX-ENERGY"].trading_date == D2
    assert f"Index US-IDX start_date={D1.isoformat()} first_row={D1.isoformat()}" in caplog.text


def test_initialize_indices_later_start_and_below_minimum_do_not_block() -> None:
    result = _result("US-IDX")
    result.series["US-IDX-ENERGY"] = IndexSeries("US-IDX-ENERGY", D2, _levels(D2))
    result.below_minimum = {"US-IDX-TINY"}
    with patch("compute_indices.load_index_tickers", return_value={"US-IDX", "US-IDX-TINY"}):
        with patch("compute_indices.load_distinct_week_starts", return_value=[W1, W2]):
            with patch("compute_indices.compute_index_series", return_value=result), patch(
                "compute_indices.write_index_weeks",
                return_value=IndexWriteResult([_row(D1)]),
            ) as mock_write:
                written, failed = initialize_indices(
                    "postgresql://example", country=CountrySet.US, settings=SETTINGS
                )

    assert (written, failed) == (1, [])
    levels = mock_write.call_args.args[1]
    assert "US-IDX-ENERGY" not in levels[W1]
    assert levels[W2]["US-IDX-ENERGY"].levels.current_price == Decimal("100.0")


def test_initialize_indices_leaves_country_unchanged_when_stored_index_has_no_series(
    _stub_io, caplog
) -> None:
    _stub_io[1].return_value = {"US-IDX", "US-IDX-ENERGY", "US-IDX-TINY"}
    with patch("compute_indices.load_distinct_week_starts", return_value=[W1]):
        with patch(
            "compute_indices.compute_index_series",
            return_value=_result("US-IDX", below={"US-IDX-TINY"}),
        ), patch("compute_indices.write_index_weeks") as mock_write:
            written, failed = initialize_indices(
                "postgresql://example", country=CountrySet.US, settings=SETTINGS
            )

    assert (written, failed) == (0, [CountrySet.US])
    mock_write.assert_not_called()
    assert "US-IDX-ENERGY" in caplog.text and "US-IDX-TINY" not in caplog.text


def test_initialize_indices_continues_after_failed_country() -> None:
    def series(entries, country, **kwargs):
        return SeriesResult() if country is CountrySet.US else _result("X")

    with patch("compute_indices.load_distinct_week_starts", return_value=[W1]):
        with patch("compute_indices.compute_index_series", side_effect=series), patch(
            "compute_indices.write_index_weeks",
            return_value=IndexWriteResult([_row(D1)]),
        ) as mock_write:
            written, failed = initialize_indices("postgresql://example", settings=SETTINGS)

    assert failed == [CountrySet.US]
    assert written == 2
    assert [c.kwargs["country"] for c in mock_write.call_args_list] == [
        CountrySet.SWE,
        CountrySet.UK,
    ]


def test_initialize_indices_skips_country_without_metrics() -> None:
    with patch("compute_indices.load_distinct_week_starts", return_value=[]):
        with patch("compute_indices.compute_index_series") as mock_series:
            assert initialize_indices(
                "postgresql://example", country=CountrySet.UK, settings=SETTINGS
            ) == (0, [])

    mock_series.assert_not_called()


def _outlier(week_start: date) -> OutlierRow:
    return OutlierRow(
        country="us",
        ticker="WYLD",
        company="Wyld",
        week_start=week_start,
        trading_date=week_start,
        prev_close=Decimal("0.0041"),
        close=Decimal("1.95"),
        price_growth=Decimal("474.6"),
        sma_50_growth=Decimal("0.1"),
        sma_200_growth=Decimal("0.01"),
        bound="price_growth > 4",
        is_new=True,
    )


def test_initialize_indices_logs_outliers(_stub_io, caplog) -> None:
    _stub_io[0].return_value = [_outlier(W2)]
    with patch("compute_indices.load_distinct_week_starts", return_value=[W1, W2]):
        with patch(
            "compute_indices.compute_index_series", return_value=_result("US-IDX")
        ), patch("compute_indices.write_index_weeks", return_value=IndexWriteResult([])):
            with caplog.at_level("WARNING", logger="compute_indices"):
                initialize_indices(
                    "postgresql://example", country=CountrySet.US, settings=SETTINGS
                )

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("WYLD" in w and W2.isoformat() in w for w in warnings)


def test_parser_accepts_country() -> None:
    assert build_parser().parse_args(["--country", "uk"]).country == "uk"


def test_main_initializes_with_country_and_settings_from_config(caplog) -> None:
    config = _mock_config(index_start_date=date(2025, 10, 10), index_min_components=3)
    with patch("compute_indices.get_config", return_value=config):
        with patch(
            "compute_indices.initialize_indices", return_value=(12, [])
        ) as mock_init:
            with caplog.at_level("INFO", logger="compute_indices"):
                assert main(["--country", "swe"]) == 0

    mock_init.assert_called_once_with(
        "postgresql://example",
        country=CountrySet.SWE,
        settings=AnchorSettings.from_config(config),
    )
    settings = mock_init.call_args.kwargs["settings"]
    assert (settings.start_date, settings.min_components) == (date(2025, 10, 10), 3)
    assert "index_rows=12" in caplog.text


def test_main_runs_all_countries_without_flag() -> None:
    with patch("compute_indices.get_config", return_value=_mock_config()):
        with patch("compute_indices.initialize_indices", return_value=(0, [])) as mock_init:
            assert main([]) == 0

    assert mock_init.call_args.kwargs["country"] is None


def test_main_returns_1_when_a_country_failed() -> None:
    with patch("compute_indices.get_config", return_value=_mock_config()):
        with patch(
            "compute_indices.initialize_indices", return_value=(5, [CountrySet.UK])
        ):
            assert main([]) == 1


def test_main_returns_1_on_db_error() -> None:
    with patch("compute_indices.get_config", return_value=_mock_config()):
        with patch("compute_indices.initialize_indices", side_effect=RuntimeError("down")):
            assert main([]) == 1


@pytest.mark.parametrize(
    ("growths", "expected"),
    [
        ({"price_growth": Decimal("9.0")}, None),
        ({"price_growth": Decimal("9.01")}, "price_growth > 9"),
        ({"price_growth": Decimal("4.5")}, None),
        ({"price_growth": Decimal("-0.999")}, None),
        ({"price_growth": Decimal("-0.9")}, None),
        ({"price_growth": Decimal("-0.9991")}, "price_growth < -0.999"),
        ({"price_growth": None, "sma_50_growth": Decimal("49")}, "sma_50_growth > 9"),
        ({"price_growth": None, "sma_50_growth": None}, None),
    ],
)
def test_is_outlier_bounds(growths: dict, expected: str | None) -> None:
    assert is_outlier(growths, max_growth=9.0, min_growth=-0.999) == expected
