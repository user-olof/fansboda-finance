"""Tests for PRD §5.8 equal-weighted market and sector indices (RFC-015 / 016 / 017 / 018)."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest

from compute_indices import build_parser, main, refresh_indices
from config import BaseConfig
from db.country import CountrySet
from db.indices import (
    BASE_WEEK_STATS_SQL,
    CHAINED_WEEK_STATS_SQL,
    DELETE_COUNTRY_INDICES_SQL,
    DELETE_COUNTRY_WEEK_SQL,
    DELETE_STALE_INDICES_SQL,
    GAP_WEEK_STATS_SQL,
    INSERT_INDEX_SQL,
    LOAD_PREVIOUS_INDICES_SQL,
    purge_stale_indices,
    write_index_weeks,
)
from equity_index import (
    BASE_INDEX_PRICE,
    COUNTRY_CURRENCY,
    INDEX_DEFINITIONS,
    IndexLevels,
    IndexRow,
    build_base_row,
    build_chained_row,
    index_momentum,
    is_outlier,
    sector_index_definition,
    with_sector_z_scores,
)
from models import OutlierRow

US = INDEX_DEFINITIONS[CountrySet.US]
W1 = date(2026, 6, 1)
W2 = date(2026, 6, 8)
W3 = date(2026, 6, 15)
D1 = date(2026, 6, 5)
D2 = date(2026, 6, 12)
BOUNDS = (Decimal("-0.999"), Decimal("9.0")) * 3


def _mock_config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {"database_url": "postgresql://example"}
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


def _mock_conn(
    fetchall: list[object] | None = None, fetchone: list[object] | None = None
) -> tuple[MagicMock, MagicMock]:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = fetchall or []
    mock_cursor.fetchone.side_effect = fetchone or []
    mock_cursor.rowcount = 0
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn, mock_cursor


def test_index_definitions_match_prd() -> None:
    assert {(d.ticker, d.name) for d in INDEX_DEFINITIONS.values()} == {
        ("US-IDX", "US Equity Index"),
        ("SWE-IDX", "OMX Equity Index"),
        ("UK-IDX", "FTSE Equity Index"),
    }
    for country, definition in INDEX_DEFINITIONS.items():
        assert definition.country is country


def test_index_momentum() -> None:
    assert index_momentum(Decimal("110"), Decimal("100")) == Decimal("1.1")
    assert index_momentum(Decimal("110"), Decimal("0")) is None


def test_build_base_row_anchors_sma_levels_to_price_ratio() -> None:
    row = build_base_row(
        US,
        trading_date=D1,
        ticker_count=4,
        avg_sma_50_ratio=Decimal("0.95"),
        avg_sma_200_ratio=Decimal("0.90"),
    )
    assert row is not None
    assert row.trading_date == D1
    assert row.ticker_count == 4
    assert row.current_price == BASE_INDEX_PRICE
    assert row.sma_50 == Decimal("95.00")
    assert row.sma_200 == Decimal("90.00")
    assert row.momentum == Decimal("95") / Decimal("90")
    assert (row.ticker, row.sector, row.country) == (
        "US-IDX",
        "US Equity Index",
        CountrySet.US,
    )


def test_build_chained_row_grows_each_level_independently() -> None:
    previous = IndexLevels(Decimal("100"), Decimal("95"), Decimal("90"))
    row = build_chained_row(
        US,
        previous,
        trading_date=D2,
        ticker_count=3,
        growth_price=Decimal("0.10"),
        growth_sma_50=Decimal("0.02"),
        growth_sma_200=Decimal("0.01"),
    )
    assert row is not None
    assert row.current_price == Decimal("110.00")
    assert row.sma_50 == Decimal("96.90")
    assert row.sma_200 == Decimal("90.90")
    assert row.momentum == Decimal("96.90") / Decimal("90.90")
    assert row.levels == IndexLevels(row.current_price, row.sma_50, row.sma_200)


def test_equal_weighting_ignores_price_level() -> None:
    """A $1000 stock up 10% and a $10 stock down 10% leave the price level flat."""
    growth = (
        (Decimal("1100") / Decimal("1000") - 1) + (Decimal("9") / Decimal("10") - 1)
    ) / 2
    row = build_chained_row(
        US,
        IndexLevels(Decimal("100"), Decimal("95"), Decimal("90")),
        trading_date=D2,
        ticker_count=2,
        growth_price=growth,
        growth_sma_50=Decimal("0"),
        growth_sma_200=Decimal("0"),
    )
    assert row is not None
    assert row.current_price == Decimal("100")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trading_date": D1, "ticker_count": 0, "avg_sma_50_ratio": None, "avg_sma_200_ratio": None},
        {"trading_date": None, "ticker_count": 2, "avg_sma_50_ratio": Decimal("1"), "avg_sma_200_ratio": Decimal("1")},
        {"trading_date": D1, "ticker_count": 2, "avg_sma_50_ratio": None, "avg_sma_200_ratio": Decimal("1")},
    ],
)
def test_build_base_row_skips_week_without_contributors(kwargs: dict) -> None:
    assert build_base_row(US, **kwargs) is None


def test_build_chained_row_skips_week_without_contributors() -> None:
    previous = IndexLevels(Decimal("100"), Decimal("95"), Decimal("90"))
    assert (
        build_chained_row(
            US,
            previous,
            trading_date=None,
            ticker_count=0,
            growth_price=None,
            growth_sma_50=None,
            growth_sma_200=None,
        )
        is None
    )


@pytest.mark.parametrize("country", list(CountrySet))
def test_index_sql_targets_country_metrics(country: CountrySet) -> None:
    prefix = country.value
    sector_key = "NULLIF(lower(replace(btrim(t.sector), ' ', '-')), '') AS sector"
    base = " ".join(BASE_WEEK_STATS_SQL[country].split())
    assert f"FROM {prefix}_metrics m JOIN {prefix}_tickers t ON t.symbol = m.ticker" in base
    assert sector_key in base
    assert "AVG(sma_50 / current_price)" in base
    assert "AVG(sma_200 / current_price)" in base
    assert "m.current_price > 0 AND m.sma_50 > 0 AND m.sma_200 > 0" in base
    assert "GROUP BY GROUPING SETS ((), (sector))" in base
    assert "100.0 * AVG(CASE WHEN sma_50 > sma_200 THEN 1 ELSE 0 END)" in base
    assert base.count("%s") == 1
    chained = " ".join(CHAINED_WEEK_STATS_SQL[country].split())
    assert f"FROM {prefix}_metrics m JOIN {prefix}_tickers t ON t.symbol = m.ticker" in chained
    assert "m.current_price > 0 AND m.sma_50 > 0 AND m.sma_200 > 0" in chained
    for growth in ("price_growth", "sma_50_growth", "sma_200_growth"):
        assert f"AVG({growth})" in chained
        assert f"m.{growth} BETWEEN %s AND %s" in chained
    assert "GROUP BY GROUPING SETS ((), (sector))" in chained
    assert chained.count("%s") == 7
    gap = " ".join(GAP_WEEK_STATS_SQL[country].split())
    assert f"FROM {prefix}_metrics cur JOIN {prefix}_metrics prev" in gap
    assert f"JOIN {prefix}_tickers t ON t.symbol = cur.ticker" in gap
    assert "(%s::text IS NULL OR NULLIF(lower(replace(btrim(t.sector), ' ', '-')), '') = %s)" in gap
    for measure in ("current_price", "sma_50", "sma_200"):
        assert f"AVG(cur.{measure} / prev.{measure} - 1)" in gap
        assert f"prev.{measure} > 0" in gap
        assert f"cur.{measure} / prev.{measure} - 1 BETWEEN %s AND %s" in gap
    assert "MAX(cur.trading_date)" in gap
    assert gap.count("%s") == 10


def test_static_index_sql_is_parameterized() -> None:
    assert INSERT_INDEX_SQL.count("%s") == 12
    for column in ("sector", "currency", "pct_uptrend", "z_score"):
        assert column in INSERT_INDEX_SQL
    assert "name" not in INSERT_INDEX_SQL
    load = " ".join(LOAD_PREVIOUS_INDICES_SQL.split())
    assert "DISTINCT ON (ticker)" in load
    assert "WHERE country = %s AND trading_date < %s" in load
    assert " ".join(DELETE_COUNTRY_WEEK_SQL.split()) == (
        "DELETE FROM indices WHERE country = %s AND trading_date >= %s "
        "AND trading_date < %s"
    )
    assert DELETE_COUNTRY_INDICES_SQL == "DELETE FROM indices WHERE country = %s"
    assert DELETE_STALE_INDICES_SQL == "DELETE FROM indices WHERE trading_date < %s"


def _inserted(mock_cursor: MagicMock) -> list[tuple]:
    return [
        c.args[1]
        for c in mock_cursor.execute.call_args_list
        if c.args[0] == INSERT_INDEX_SQL
    ]


def test_write_index_weeks_base_then_chained_week() -> None:
    mock_conn, mock_cursor = _mock_conn(
        fetchall=[
            [],  # no previous rows before W1
            [(1, None, 3, D1, Decimal("0.95"), Decimal("0.90"), Decimal("66.7"))],
            [(1, None, 0, None, None, None, None, None)],
            [("US-IDX", D1, Decimal("100"), Decimal("95"), Decimal("90"))],
            [(1, None, 3, D2, Decimal("0.95"), Decimal("0.90"), Decimal("66.7"))],
            [(1, None, 2, D2, Decimal("0.1"), Decimal("0.02"), Decimal("0.01"), Decimal("50"))],
        ]
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        rows = write_index_weeks(
            "postgresql://example", [W2, W1], country=CountrySet.US, rebuild=True
        )

    assert [(r.trading_date, r.current_price, r.sma_50, r.sma_200) for r in rows] == [
        (D1, Decimal("100"), Decimal("95.00"), Decimal("90.00")),
        (D2, Decimal("110.0"), Decimal("96.90"), Decimal("90.90")),
    ]
    executed = mock_cursor.execute.call_args_list
    assert executed[0] == call(DELETE_COUNTRY_INDICES_SQL, ("us",))
    assert executed[1] == call(LOAD_PREVIOUS_INDICES_SQL, ("us", W1))
    assert executed[2] == call(BASE_WEEK_STATS_SQL[CountrySet.US], (W1,))
    assert executed[3] == call(CHAINED_WEEK_STATS_SQL[CountrySet.US], (W1, *BOUNDS))
    assert executed[4] == call(DELETE_COUNTRY_WEEK_SQL, ("us", W1, W2))
    assert executed[5] == call(
        INSERT_INDEX_SQL,
        (
            "US-IDX",
            "US Equity Index",
            "us",
            "USD",
            D1,
            3,
            Decimal("100"),
            Decimal("95.00"),
            Decimal("90.00"),
            Decimal("66.7"),
            Decimal("95.00") / Decimal("90.00"),
            None,
        ),
    )
    assert executed[9] == call(DELETE_COUNTRY_WEEK_SQL, ("us", W2, W3))
    assert _inserted(mock_cursor)[1][9] == Decimal("50")
    mock_conn.commit.assert_called_once()


def test_write_index_weeks_builds_sector_indices_with_z_scores() -> None:
    """Market chains; an existing sector chains; a new sector gets its base week."""
    previous = [
        ("US-IDX", D1, Decimal("100"), Decimal("95"), Decimal("90")),
        ("US-IDX-TECHNOLOGY", D1, Decimal("100"), Decimal("100"), Decimal("100")),
    ]
    base = [
        (1, None, 3, D2, Decimal("1"), Decimal("1"), Decimal("50")),
        (0, "energy", 1, D2, Decimal("0.9"), Decimal("1"), Decimal("0")),
        (0, "technology", 2, D2, Decimal("1"), Decimal("1"), Decimal("100")),
        (0, None, 0, D2, Decimal("1"), Decimal("1"), Decimal("0")),  # blank sector
    ]
    chained = [
        (1, None, 3, D2, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("50")),
        (0, "technology", 2, D2, Decimal("0.1"), Decimal("0.2"), Decimal("0"), Decimal("100")),
    ]
    mock_conn, mock_cursor = _mock_conn(fetchall=[previous, base, chained])

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        rows = write_index_weeks("postgresql://example", [W2], country=CountrySet.US)

    by_ticker = {row.ticker: row for row in rows}
    assert list(by_ticker) == ["US-IDX", "US-IDX-ENERGY", "US-IDX-TECHNOLOGY"]
    market = by_ticker["US-IDX"]
    assert (market.sector, market.sector_key, market.currency, market.z_score) == (
        "US Equity Index",
        None,
        "USD",
        None,
    )
    energy = by_ticker["US-IDX-ENERGY"]
    assert (energy.sector, energy.sector_key) == ("Energy", "energy")
    assert (energy.current_price, energy.sma_50, energy.sma_200) == (
        Decimal("100"),
        Decimal("90.0"),
        Decimal("100"),
    )
    tech = by_ticker["US-IDX-TECHNOLOGY"]
    assert (tech.current_price, tech.sma_50, tech.sma_200) == (
        Decimal("110.0"),
        Decimal("120.0"),
        Decimal("100"),
    )
    assert tech.pct_uptrend == Decimal("100")
    # Two sectors with momentum 0.9 and 1.2: z = ±1 (population std).
    assert energy.z_score == Decimal("-1")
    assert tech.z_score == Decimal("1")
    assert len(_inserted(mock_cursor)) == 3


def test_write_index_weeks_uses_week_of_previous_trading_date() -> None:
    """A previous row dated Thursday still maps to its Monday week."""
    mock_conn, mock_cursor = _mock_conn(
        fetchall=[
            [("UK-IDX", date(2026, 6, 4), Decimal("100"), Decimal("95"), Decimal("90"))],
            [(1, None, 1, D2, Decimal("1"), Decimal("1"), Decimal("0"))],
            [(1, None, 1, D2, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))],
        ]
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        rows = write_index_weeks("postgresql://example", [W2], country=CountrySet.UK)

    assert rows[0].current_price == Decimal("100")
    assert rows[0].currency == "GBP"
    sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
    assert GAP_WEEK_STATS_SQL[CountrySet.UK] not in sqls


def test_write_index_weeks_gap_week_uses_stored_row_ratio() -> None:
    """Previous index row two weeks back: fall back to the ratio query (FR-37a)."""
    mock_conn, mock_cursor = _mock_conn(
        fetchall=[
            [("US-IDX", D1, Decimal("100"), Decimal("95"), Decimal("90"))],
            [(1, None, 2, date(2026, 6, 19), Decimal("1"), Decimal("1"), Decimal("0"))],
            [(1, None, 0, None, None, None, None, None)],
        ],
        fetchone=[(2, date(2026, 6, 19), Decimal("0.05"), Decimal("0"), Decimal("0"), Decimal("50"))],
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        rows = write_index_weeks(
            "postgresql://example",
            [W3],
            country=CountrySet.US,
            max_growth=1.0,
            min_growth=-0.5,
        )

    assert call(
        GAP_WEEK_STATS_SQL[CountrySet.US],
        (W1, W3, None, None, *((Decimal("-0.5"), Decimal("1.0")) * 3)),
    ) in mock_cursor.execute.call_args_list
    assert rows[0].current_price == Decimal("105.00")
    assert rows[0].pct_uptrend == Decimal("50")


def test_write_index_weeks_gap_week_filters_sector() -> None:
    mock_conn, mock_cursor = _mock_conn(
        fetchall=[
            [("SWE-IDX-ENERGY", D1, Decimal("100"), Decimal("95"), Decimal("90"))],
            [
                (1, None, 1, D2, Decimal("1"), Decimal("1"), Decimal("0")),
                (0, "energy", 1, D2, Decimal("1"), Decimal("1"), Decimal("0")),
            ],
            [],
        ],
        fetchone=[(1, D2, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))],
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        write_index_weeks("postgresql://example", [W3], country=CountrySet.SWE)

    gap_calls = [
        c.args[1]
        for c in mock_cursor.execute.call_args_list
        if c.args[0] == GAP_WEEK_STATS_SQL[CountrySet.SWE]
    ]
    assert [args[:4] for args in gap_calls] == [(W1, W3, "energy", "energy")]


def test_write_index_weeks_removes_week_without_contributors() -> None:
    mock_conn, mock_cursor = _mock_conn(
        fetchall=[
            [("SWE-IDX", D1, Decimal("100"), Decimal("95"), Decimal("90"))],
            [(1, None, 0, None, None, None, None)],
            [(1, None, 0, None, None, None, None, None)],
        ]
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        rows = write_index_weeks("postgresql://example", [W2], country=CountrySet.SWE)

    assert rows == []
    sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
    assert INSERT_INDEX_SQL not in sqls
    assert DELETE_COUNTRY_INDICES_SQL not in sqls
    assert mock_cursor.execute.call_args_list[-1] == call(
        DELETE_COUNTRY_WEEK_SQL, ("swe", W2, W3)
    )


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
        "US Equity Index",
        CountrySet.US,
        trading_date,
        2,
        Decimal("100"),
        Decimal("95"),
        Decimal("90"),
        Decimal("95") / Decimal("90"),
    )


@pytest.fixture(autouse=True)
def _stub_outliers():
    with patch("compute_indices.load_outliers", return_value=[]) as mock:
        yield mock


def test_refresh_indices_full_rebuild_uses_all_weeks() -> None:
    with patch(
        "compute_indices.load_distinct_week_starts", return_value=[W1, W2]
    ):
        with patch(
            "compute_indices.write_index_weeks", return_value=[_row(W1), _row(W2)]
        ) as mock_write:
            written = refresh_indices("postgresql://example", country=CountrySet.US)

    assert written == 2
    mock_write.assert_called_once_with(
        "postgresql://example",
        [W1, W2],
        country=CountrySet.US,
        rebuild=True,
        max_growth=9.0,
        min_growth=-0.999,
    )


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


def test_refresh_indices_logs_outliers_but_not_in_rebuild_base_week(
    _stub_outliers, caplog
) -> None:
    _stub_outliers.return_value = [_outlier(W1), _outlier(W2)]
    with patch("compute_indices.load_distinct_week_starts", return_value=[W1, W2]):
        with patch("compute_indices.write_index_weeks", return_value=[]):
            with caplog.at_level("WARNING", logger="compute_indices"):
                refresh_indices(
                    "postgresql://example",
                    country=CountrySet.US,
                    max_growth=2.0,
                    min_growth=-0.5,
                )

    _stub_outliers.assert_called_once_with(
        "postgresql://example",
        [W1, W2],
        country=CountrySet.US,
        max_growth=2.0,
        min_growth=-0.5,
    )
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "WYLD" in warnings[0] and W2.isoformat() in warnings[0]


def test_refresh_indices_recomputes_from_earliest_given_week() -> None:
    with patch(
        "compute_indices.load_distinct_week_starts", return_value=[W1, W2, W3]
    ):
        with patch(
            "compute_indices.write_index_weeks", return_value=[_row(W2)]
        ) as mock_write:
            written = refresh_indices("postgresql://example", [W2])

    assert written == 3
    assert mock_write.call_args_list == [
        call(
            "postgresql://example",
            [W2, W3],
            country=c,
            rebuild=False,
            max_growth=9.0,
            min_growth=-0.999,
        )
        for c in CountrySet
    ]


def test_refresh_indices_empty_weeks_is_noop() -> None:
    with patch("compute_indices.load_distinct_week_starts", return_value=[W1]):
        with patch("compute_indices.write_index_weeks") as mock_write:
            assert refresh_indices("postgresql://example", []) == 0

    mock_write.assert_not_called()


def test_refresh_indices_skips_country_without_metrics() -> None:
    with patch("compute_indices.load_distinct_week_starts", return_value=[]):
        with patch("compute_indices.write_index_weeks") as mock_write:
            assert refresh_indices("postgresql://example") == 0

    mock_write.assert_not_called()


def test_parser_accepts_country() -> None:
    assert build_parser().parse_args(["--country", "uk"]).country == "uk"


def test_main_rebuilds_with_country(caplog) -> None:
    with patch("compute_indices.get_config", return_value=_mock_config()):
        with patch("compute_indices.refresh_indices", return_value=12) as mock_refresh:
            with caplog.at_level("INFO", logger="compute_indices"):
                assert main(["--country", "swe"]) == 0

    mock_refresh.assert_called_once_with(
        "postgresql://example",
        None,
        country=CountrySet.SWE,
        max_growth=9.0,
        min_growth=-0.999,
    )
    assert "index_rows=12" in caplog.text


def test_main_returns_1_on_db_error() -> None:
    with patch("compute_indices.get_config", return_value=_mock_config()):
        with patch("compute_indices.refresh_indices", side_effect=RuntimeError("down")):
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
