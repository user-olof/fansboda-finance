"""Tests for PRD §5.8 equal-weighted country indices (RFC-015 / 016 / 017)."""

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
    DELETE_INDEX_SQL,
    DELETE_INDEX_WEEK_SQL,
    DELETE_STALE_INDICES_SQL,
    GAP_WEEK_STATS_SQL,
    INSERT_INDEX_SQL,
    LOAD_PREVIOUS_INDEX_SQL,
    purge_stale_indices,
    write_index_weeks,
)
from equity_index import (
    BASE_INDEX_PRICE,
    INDEX_DEFINITIONS,
    IndexLevels,
    IndexRow,
    build_base_row,
    build_chained_row,
    index_momentum,
    is_outlier,
)
from models import OutlierRow

US = INDEX_DEFINITIONS[CountrySet.US]
W1 = date(2026, 6, 1)
W2 = date(2026, 6, 8)
W3 = date(2026, 6, 15)
D1 = date(2026, 6, 5)
D2 = date(2026, 6, 12)
BOUNDS = (Decimal("-0.8"), Decimal("4.0")) * 3


def _mock_config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {"database_url": "postgresql://example"}
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


def _mock_conn(fetchone: list[object]) -> tuple[MagicMock, MagicMock]:
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = fetchone
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
    assert (row.ticker, row.name, row.country) == (
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
    base = " ".join(BASE_WEEK_STATS_SQL[country].split())
    assert f"FROM {prefix}_metrics" in base
    assert "AVG(sma_50 / current_price)" in base
    assert "AVG(sma_200 / current_price)" in base
    assert "current_price > 0 AND sma_50 > 0 AND sma_200 > 0" in base
    chained = " ".join(CHAINED_WEEK_STATS_SQL[country].split())
    assert f"FROM {prefix}_metrics WHERE week_start = %s" in chained
    assert "JOIN" not in chained
    assert "current_price > 0 AND sma_50 > 0 AND sma_200 > 0" in chained
    for growth in ("price_growth", "sma_50_growth", "sma_200_growth"):
        assert f"AVG({growth})" in chained
        assert f"{growth} BETWEEN %s AND %s" in chained
    assert chained.count("%s") == 7
    gap = " ".join(GAP_WEEK_STATS_SQL[country].split())
    assert f"FROM {prefix}_metrics cur JOIN {prefix}_metrics prev" in gap
    for measure in ("current_price", "sma_50", "sma_200"):
        assert f"AVG(cur.{measure} / prev.{measure} - 1)" in gap
        assert f"prev.{measure} > 0" in gap
        assert f"cur.{measure} / prev.{measure} - 1 BETWEEN %s AND %s" in gap
    assert "MAX(cur.trading_date)" in gap
    assert gap.count("%s") == 8


def test_static_index_sql_is_parameterized() -> None:
    assert INSERT_INDEX_SQL.count("%s") == 9
    assert "trading_date < %s" in LOAD_PREVIOUS_INDEX_SQL
    assert " ".join(DELETE_INDEX_WEEK_SQL.split()) == (
        "DELETE FROM indices WHERE ticker = %s AND trading_date >= %s "
        "AND trading_date < %s"
    )
    assert DELETE_STALE_INDICES_SQL == "DELETE FROM indices WHERE trading_date < %s"


def test_write_index_weeks_base_then_chained_week() -> None:
    mock_conn, mock_cursor = _mock_conn(
        [
            None,  # no previous row before W1
            (3, D1, Decimal("0.95"), Decimal("0.90")),  # base stats W1
            (D1, Decimal("100"), Decimal("95"), Decimal("90")),  # previous row
            (2, D2, Decimal("0.1"), Decimal("0.02"), Decimal("0.01")),  # W2 growth
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
    assert executed[0] == call(DELETE_INDEX_SQL, ("US-IDX",))
    assert executed[1] == call(LOAD_PREVIOUS_INDEX_SQL, ("US-IDX", W1))
    assert executed[2] == call(BASE_WEEK_STATS_SQL[CountrySet.US], (W1,))
    assert executed[3] == call(DELETE_INDEX_WEEK_SQL, ("US-IDX", W1, W2))
    assert executed[4] == call(
        INSERT_INDEX_SQL,
        (
            "US-IDX",
            "US Equity Index",
            "us",
            D1,
            3,
            Decimal("100"),
            Decimal("95.00"),
            Decimal("90.00"),
            Decimal("95.00") / Decimal("90.00"),
        ),
    )
    assert executed[6] == call(CHAINED_WEEK_STATS_SQL[CountrySet.US], (W2, *BOUNDS))
    assert executed[7] == call(DELETE_INDEX_WEEK_SQL, ("US-IDX", W2, W3))
    mock_conn.commit.assert_called_once()


def test_write_index_weeks_uses_week_of_previous_trading_date() -> None:
    """A previous row dated Thursday still maps to its Monday week."""
    mock_conn, mock_cursor = _mock_conn(
        [
            (date(2026, 6, 4), Decimal("100"), Decimal("95"), Decimal("90")),
            (1, D2, Decimal("0"), Decimal("0"), Decimal("0")),
        ]
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        write_index_weeks("postgresql://example", [W2], country=CountrySet.UK)

    assert mock_cursor.execute.call_args_list[1] == call(
        CHAINED_WEEK_STATS_SQL[CountrySet.UK], (W2, *BOUNDS)
    )


def test_write_index_weeks_gap_week_uses_stored_row_ratio() -> None:
    """Previous index row two weeks back: fall back to the ratio query (FR-37a)."""
    mock_conn, mock_cursor = _mock_conn(
        [
            (D1, Decimal("100"), Decimal("95"), Decimal("90")),
            (2, date(2026, 6, 19), Decimal("0.05"), Decimal("0"), Decimal("0")),
        ]
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        rows = write_index_weeks(
            "postgresql://example",
            [W3],
            country=CountrySet.US,
            max_growth=1.0,
            min_growth=-0.5,
        )

    assert mock_cursor.execute.call_args_list[1] == call(
        GAP_WEEK_STATS_SQL[CountrySet.US],
        (W1, W3, *((Decimal("-0.5"), Decimal("1.0")) * 3)),
    )
    assert rows[0].current_price == Decimal("105.00")


def test_write_index_weeks_removes_week_without_contributors() -> None:
    mock_conn, mock_cursor = _mock_conn(
        [(D1, Decimal("100"), Decimal("95"), Decimal("90")), (0, None, None, None, None)]
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        rows = write_index_weeks("postgresql://example", [W2], country=CountrySet.SWE)

    assert rows == []
    sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
    assert INSERT_INDEX_SQL not in sqls
    assert DELETE_INDEX_SQL not in sqls
    assert mock_cursor.execute.call_args_list[-1] == call(
        DELETE_INDEX_WEEK_SQL, ("SWE-IDX", W2, W3)
    )


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
        max_growth=4.0,
        min_growth=-0.8,
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
            max_growth=4.0,
            min_growth=-0.8,
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
        max_growth=4.0,
        min_growth=-0.8,
    )
    assert "index_rows=12" in caplog.text


def test_main_returns_1_on_db_error() -> None:
    with patch("compute_indices.get_config", return_value=_mock_config()):
        with patch("compute_indices.refresh_indices", side_effect=RuntimeError("down")):
            assert main([]) == 1


@pytest.mark.parametrize(
    ("growths", "expected"),
    [
        ({"price_growth": Decimal("4.0")}, None),
        ({"price_growth": Decimal("4.01")}, "price_growth > 4"),
        ({"price_growth": Decimal("-0.8")}, None),
        ({"price_growth": Decimal("-0.81")}, "price_growth < -0.8"),
        ({"price_growth": None, "sma_50_growth": Decimal("49")}, "sma_50_growth > 4"),
        ({"price_growth": None, "sma_50_growth": None}, None),
    ],
)
def test_is_outlier_bounds(growths: dict, expected: str | None) -> None:
    assert is_outlier(growths, max_growth=4.0, min_growth=-0.8) == expected
