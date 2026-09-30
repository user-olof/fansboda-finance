"""Tests for PRD §5.7 sector trend aggregation."""

from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from compute_sector_trends import build_parser, main, refresh_sector_trends
from config import BaseConfig
from db.country import CountrySet
from db.sector import (
    DELETE_SECTOR_WEEK_SQL,
    INSERT_SECTOR_WEEK_SQL,
    PRUNE_ORPHAN_SECTOR_WEEKS_SQL,
    prune_orphan_sector_weeks,
    refresh_sector_weeks,
)


def _mock_config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {"database_url": "postgresql://example"}
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


def _mock_conn(rowcount: int = 0) -> tuple[MagicMock, MagicMock]:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = rowcount
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn, mock_cursor


@pytest.mark.parametrize("country", list(CountrySet))
def test_sector_sql_targets_country_tables(country: CountrySet) -> None:
    prefix = country.value
    insert_sql = INSERT_SECTOR_WEEK_SQL[country]
    assert f"INSERT INTO {prefix}_by_sector" in insert_sql
    assert f"FROM {prefix}_metrics m" in insert_sql
    assert f"JOIN {prefix}_tickers t" in insert_sql
    assert f"DELETE FROM {prefix}_by_sector WHERE week_start = %s" == (
        DELETE_SECTOR_WEEK_SQL[country]
    )
    prune_sql = PRUNE_ORPHAN_SECTOR_WEEKS_SQL[country]
    assert f"DELETE FROM {prefix}_by_sector" in prune_sql
    assert f"FROM {prefix}_metrics m" in prune_sql


def test_insert_sql_is_equal_weighted_and_normalizes_sector() -> None:
    sql = " ".join(INSERT_SECTOR_WEEK_SQL[CountrySet.US].split())
    assert "lower(replace(btrim(t.sector), ' ', '-'))" in sql
    assert "AVG(m.momentum)" in sql
    assert "percentile_cont(0.5) WITHIN GROUP (ORDER BY m.momentum)" in sql
    assert "AVG(m.z_score)" in sql
    assert "100.0 * AVG(CASE WHEN m.sma_50 > m.sma_200 THEN 1 ELSE 0 END)" in sql
    assert "m.momentum IS NOT NULL" in sql
    assert "t.sector IS NOT NULL" in sql
    assert sql.count("%s") == 1


def test_refresh_sector_weeks_replaces_each_week_in_one_transaction() -> None:
    mock_conn, mock_cursor = _mock_conn(rowcount=4)
    weeks = [date(2026, 6, 1), date(2026, 6, 8)]

    with patch("db.sector.psycopg2.connect", return_value=mock_conn):
        written = refresh_sector_weeks(
            "postgresql://example", weeks, country=CountrySet.SWE
        )

    assert written == 8
    assert mock_cursor.execute.call_args_list == [
        call(DELETE_SECTOR_WEEK_SQL[CountrySet.SWE], (date(2026, 6, 1),)),
        call(INSERT_SECTOR_WEEK_SQL[CountrySet.SWE], (date(2026, 6, 1),)),
        call(DELETE_SECTOR_WEEK_SQL[CountrySet.SWE], (date(2026, 6, 8),)),
        call(INSERT_SECTOR_WEEK_SQL[CountrySet.SWE], (date(2026, 6, 8),)),
    ]
    mock_conn.commit.assert_called_once()


def test_prune_orphan_sector_weeks_returns_deleted_count() -> None:
    mock_conn, mock_cursor = _mock_conn(rowcount=3)

    with patch("db.sector.psycopg2.connect", return_value=mock_conn):
        assert prune_orphan_sector_weeks("postgresql://example", country=CountrySet.UK) == 3

    mock_cursor.execute.assert_called_once_with(
        PRUNE_ORPHAN_SECTOR_WEEKS_SQL[CountrySet.UK]
    )
    mock_conn.commit.assert_called_once()


def test_refresh_sector_trends_defaults_to_all_stored_weeks_per_country() -> None:
    weeks = {
        CountrySet.US: [date(2026, 6, 1)],
        CountrySet.SWE: [],
        CountrySet.UK: [date(2026, 6, 1), date(2026, 6, 8)],
    }
    with patch(
        "compute_sector_trends.load_distinct_week_starts",
        side_effect=lambda _url, *, country: weeks[country],
    ):
        with patch(
            "compute_sector_trends.refresh_sector_weeks", return_value=2
        ) as mock_refresh:
            with patch(
                "compute_sector_trends.prune_orphan_sector_weeks", return_value=1
            ) as mock_prune:
                written, pruned = refresh_sector_trends("postgresql://example")

    assert (written, pruned) == (4, 3)
    assert mock_refresh.call_args_list == [
        call("postgresql://example", [date(2026, 6, 1)], country=CountrySet.US),
        call(
            "postgresql://example",
            [date(2026, 6, 1), date(2026, 6, 8)],
            country=CountrySet.UK,
        ),
    ]
    assert mock_prune.call_count == 3


def test_refresh_sector_trends_explicit_weeks_scoped_to_country() -> None:
    with patch("compute_sector_trends.load_distinct_week_starts") as mock_load:
        with patch(
            "compute_sector_trends.refresh_sector_weeks", return_value=5
        ) as mock_refresh:
            with patch(
                "compute_sector_trends.prune_orphan_sector_weeks", return_value=0
            ):
                result = refresh_sector_trends(
                    "postgresql://example",
                    [date(2026, 6, 8), date(2026, 6, 1), date(2026, 6, 8)],
                    country=CountrySet.US,
                )

    assert result == (5, 0)
    mock_load.assert_not_called()
    mock_refresh.assert_called_once_with(
        "postgresql://example",
        [date(2026, 6, 1), date(2026, 6, 8)],
        country=CountrySet.US,
    )


def test_refresh_sector_trends_empty_weeks_only_prunes() -> None:
    with patch("compute_sector_trends.refresh_sector_weeks") as mock_refresh:
        with patch(
            "compute_sector_trends.prune_orphan_sector_weeks", return_value=2
        ) as mock_prune:
            assert refresh_sector_trends("postgresql://example", []) == (0, 6)

    mock_refresh.assert_not_called()
    assert mock_prune.call_count == 3


def test_parser_normalizes_week_to_monday() -> None:
    args = build_parser().parse_args(["--country", "swe", "--week", "2026-06-05"])
    assert args.country == "swe"
    assert args.week == date(2026, 6, 1)


def test_parser_rejects_invalid_week() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--week", "not-a-date"])


def test_main_passes_country_and_week(caplog) -> None:
    with patch("compute_sector_trends.get_config", return_value=_mock_config()):
        with patch(
            "compute_sector_trends.refresh_sector_trends", return_value=(7, 1)
        ) as mock_refresh:
            with caplog.at_level("INFO", logger="compute_sector_trends"):
                assert main(["--country", "uk", "--week", "2026-06-03"]) == 0

    mock_refresh.assert_called_once_with(
        "postgresql://example", [date(2026, 6, 1)], country=CountrySet.UK
    )
    assert "sector_rows=7 pruned=1" in caplog.text


def test_main_defaults_to_all_weeks_and_countries() -> None:
    with patch("compute_sector_trends.get_config", return_value=_mock_config()):
        with patch(
            "compute_sector_trends.refresh_sector_trends", return_value=(0, 0)
        ) as mock_refresh:
            assert main([]) == 0

    mock_refresh.assert_called_once_with("postgresql://example", None, country=None)


def test_main_returns_1_on_db_error() -> None:
    with patch("compute_sector_trends.get_config", return_value=_mock_config()):
        with patch(
            "compute_sector_trends.refresh_sector_trends",
            side_effect=RuntimeError("db down"),
        ):
            assert main([]) == 1
