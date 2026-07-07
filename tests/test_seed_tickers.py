from unittest.mock import MagicMock, patch

from db.tickers import upsert_tickers
from seed_tickers import seed_tickers_from_file


def test_upsert_tickers_executes_values() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 2
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    rows = [("AAA.ST", "Alpha AB", "Industrials", "Machinery"), ("BBB.ST", None, None, None)]

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        with patch("db.tickers.execute_values") as mock_execute:
            affected = upsert_tickers("postgresql://example", rows)

    mock_execute.assert_called_once()
    sql = mock_execute.call_args[0][1]
    assert "company" in sql
    assert "sector" in sql
    assert "industry" in sql
    assert "ON CONFLICT (symbol)" in sql
    assert "updated_at = NOW()" in sql
    mock_conn.commit.assert_called_once()
    assert affected == 2


def test_upsert_tickers_returns_zero_for_empty_rows() -> None:
    with patch("db.tickers.psycopg2.connect") as mock_connect:
        assert upsert_tickers("postgresql://example", []) == 0
    mock_connect.assert_not_called()


def test_seed_tickers_from_file_resolves_and_upserts(tmp_path) -> None:
    tickers_file = tmp_path / "tickers.txt"
    tickers_file.write_text("aaa.st\n# comment\n\nbbb.st\n", encoding="utf-8")

    with patch(
        "seed_tickers.resolve_watchlist_fields",
        side_effect=[
            ("Alpha AB", "Industrials", "Machinery"),
            ("Beta AB", "Technology", "Software"),
        ],
    ):
        with patch("seed_tickers.time.sleep") as mock_sleep:
            with patch("seed_tickers.upsert_tickers", return_value=2) as mock_upsert:
                count = seed_tickers_from_file(
                    "postgresql://example",
                    tickers_file,
                    name_delay=0.25,
                )

    assert count == 2
    mock_sleep.assert_called_once_with(0.25)
    mock_upsert.assert_called_once_with(
        "postgresql://example",
        [
            ("AAA.ST", "Alpha AB", "Industrials", "Machinery"),
            ("BBB.ST", "Beta AB", "Technology", "Software"),
        ],
    )


def test_seed_tickers_from_file_records_none_on_resolve_failure(tmp_path) -> None:
    tickers_file = tmp_path / "tickers.txt"
    tickers_file.write_text("aaa.st\n", encoding="utf-8")

    with patch("seed_tickers.resolve_watchlist_fields", side_effect=RuntimeError("boom")):
        with patch("seed_tickers.upsert_tickers", return_value=1) as mock_upsert:
            count = seed_tickers_from_file("postgresql://example", tickers_file)

    assert count == 1
    mock_upsert.assert_called_once_with(
        "postgresql://example",
        [("AAA.ST", None, None, None)],
    )
