"""Tests for PRD §5.8 equal-weighted country indices (RFC-015)."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest

from compute_indices import build_parser, main, refresh_indices
from config import BaseConfig
from db.country import CountrySet
from db.indices import (
    COUNT_PRICED_STOCKS_SQL,
    DELETE_INDEX_SQL,
    DELETE_INDEX_WEEK_SQL,
    DELETE_STALE_INDICES_SQL,
    LOAD_PREVIOUS_INDEX_SQL,
    UPSERT_INDEX_SQL,
    WEEKLY_RETURN_SQL,
    purge_stale_indices,
    write_index_weeks,
)
from equity_index import (
    BASE_INDEX_PRICE,
    INDEX_DEFINITIONS,
    IndexRow,
    build_index_row,
)

US = INDEX_DEFINITIONS[CountrySet.US]
W1 = date(2026, 6, 1)
W2 = date(2026, 6, 8)
W3 = date(2026, 6, 15)


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


def test_build_index_row_base_week_is_100() -> None:
    row = build_index_row(US, W1, prev_price=None, ticker_count=5, avg_return=None)
    assert row == IndexRow(
        ticker="US-IDX",
        name="US Equity Index",
        country=CountrySet.US,
        week_start=W1,
        ticker_count=5,
        avg_return=None,
        index_price=BASE_INDEX_PRICE,
    )


def test_build_index_row_chains_average_return() -> None:
    row = build_index_row(
        US, W2, prev_price=Decimal("100"), ticker_count=2, avg_return=Decimal("0.05")
    )
    assert row is not None
    assert row.index_price == Decimal("105.00")
    assert row.avg_return == Decimal("0.05")

    next_row = build_index_row(
        US, W3, prev_price=row.index_price, ticker_count=2, avg_return=Decimal("-0.1")
    )
    assert next_row is not None
    assert next_row.index_price == Decimal("94.500")


def test_equal_weighting_ignores_price_level() -> None:
    """A $1000 stock up 10% and a $10 stock down 10% net to a flat index."""
    returns = [Decimal("1100") / Decimal("1000") - 1, Decimal("9") / Decimal("10") - 1]
    avg = sum(returns) / len(returns)
    row = build_index_row(
        US, W2, prev_price=Decimal("100"), ticker_count=2, avg_return=avg
    )
    assert row is not None
    assert row.index_price == Decimal("100")


@pytest.mark.parametrize(
    ("prev_price", "ticker_count", "avg_return"),
    [
        (None, 0, None),
        (Decimal("100"), 0, None),
        (Decimal("100"), 3, None),
    ],
)
def test_build_index_row_skips_week_without_contributors(
    prev_price: Decimal | None, ticker_count: int, avg_return: Decimal | None
) -> None:
    assert (
        build_index_row(
            US,
            W1,
            prev_price=prev_price,
            ticker_count=ticker_count,
            avg_return=avg_return,
        )
        is None
    )


@pytest.mark.parametrize("country", list(CountrySet))
def test_index_sql_targets_country_metrics(country: CountrySet) -> None:
    prefix = country.value
    assert f"FROM {prefix}_metrics" in COUNT_PRICED_STOCKS_SQL[country]
    weekly = " ".join(WEEKLY_RETURN_SQL[country].split())
    assert f"FROM {prefix}_metrics cur JOIN {prefix}_metrics prev" in weekly
    assert "AVG(cur.current_price / prev.current_price - 1)" in weekly
    assert "prev.current_price > 0" in weekly
    assert weekly.count("%s") == 2


def test_static_index_sql_is_parameterized() -> None:
    assert "ON CONFLICT (ticker, week_start) DO UPDATE" in UPSERT_INDEX_SQL
    assert UPSERT_INDEX_SQL.count("%s") == 7
    assert LOAD_PREVIOUS_INDEX_SQL.count("%s") == 2
    assert DELETE_STALE_INDICES_SQL == "DELETE FROM indices WHERE week_start < %s"


def test_write_index_weeks_base_then_chained_week() -> None:
    mock_conn, mock_cursor = _mock_conn(
        [
            None,  # no previous row for W1
            (3,),  # priced stocks in W1
            (W1, Decimal("100")),  # previous row for W2
            (2, Decimal("0.1")),  # weekly return stats for W2
        ]
    )

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        rows = write_index_weeks(
            "postgresql://example", [W2, W1], country=CountrySet.US, rebuild=True
        )

    assert [(r.week_start, r.index_price, r.ticker_count) for r in rows] == [
        (W1, Decimal("100"), 3),
        (W2, Decimal("110.0"), 2),
    ]
    executed = mock_cursor.execute.call_args_list
    assert executed[0] == call(DELETE_INDEX_SQL, ("US-IDX",))
    assert executed[1] == call(LOAD_PREVIOUS_INDEX_SQL, ("US-IDX", W1))
    assert executed[2] == call(COUNT_PRICED_STOCKS_SQL[CountrySet.US], (W1,))
    assert executed[3] == call(
        UPSERT_INDEX_SQL, ("US-IDX", "US Equity Index", "us", W1, 3, None, Decimal("100"))
    )
    assert executed[5] == call(WEEKLY_RETURN_SQL[CountrySet.US], (W1, W2))
    assert executed[6] == call(
        UPSERT_INDEX_SQL,
        ("US-IDX", "US Equity Index", "us", W2, 2, Decimal("0.1"), Decimal("110.0")),
    )
    mock_conn.commit.assert_called_once()


def test_write_index_weeks_deletes_week_without_contributors() -> None:
    mock_conn, mock_cursor = _mock_conn([(W1, Decimal("100")), (0, None)])

    with patch("db.indices.psycopg2.connect", return_value=mock_conn):
        rows = write_index_weeks("postgresql://example", [W2], country=CountrySet.SWE)

    assert rows == []
    sqls = [c.args[0] for c in mock_cursor.execute.call_args_list]
    assert DELETE_INDEX_SQL not in sqls
    assert UPSERT_INDEX_SQL not in sqls
    assert mock_cursor.execute.call_args_list[-1] == call(
        DELETE_INDEX_WEEK_SQL, ("SWE-IDX", W2)
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


def _row(week: date) -> IndexRow:
    return IndexRow("US-IDX", "US Equity Index", CountrySet.US, week, 2, None, Decimal("100"))


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
        "postgresql://example", [W1, W2], country=CountrySet.US, rebuild=True
    )


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
        call("postgresql://example", [W2, W3], country=c, rebuild=False)
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
        "postgresql://example", None, country=CountrySet.SWE
    )
    assert "index_rows=12" in caplog.text


def test_main_returns_1_on_db_error() -> None:
    with patch("compute_indices.get_config", return_value=_mock_config()):
        with patch("compute_indices.refresh_indices", side_effect=RuntimeError("down")):
            assert main([]) == 1
