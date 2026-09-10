from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from db.market import purge_stale_market, upsert_market_stats
from models import MarketRow


def test_upsert_market_stats_executes_upsert() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    row = MarketRow(
        market="us_market",
        trading_date=date(2026, 6, 6),
        momentum_mean=Decimal("0.95"),
        momentum_std=Decimal("0.05"),
    )

    with patch("db.market.psycopg2.connect", return_value=mock_conn):
        affected = upsert_market_stats("postgresql://example", row)

    mock_cursor.execute.assert_called_once()
    sql = mock_cursor.execute.call_args[0][0]
    assert "INSERT INTO us_market_metrics" in sql
    assert "momentum_mean" in sql
    assert "momentum_std" in sql
    assert "ON CONFLICT (market, trading_date) DO UPDATE" in sql
    values = mock_cursor.execute.call_args[0][1]
    assert values[0] == "us_market"
    assert values[1] == date(2026, 6, 6)
    assert values[3] == Decimal("0.95")
    assert values[4] == Decimal("0.05")
    mock_conn.commit.assert_called_once()
    assert affected == 1


def test_upsert_market_stats_routes_se_market_to_swe_table() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    row = MarketRow(
        market="se_market",
        trading_date=date(2026, 6, 6),
        momentum_mean=Decimal("0.88"),
        momentum_std=Decimal("0.03"),
    )

    with patch("db.market.psycopg2.connect", return_value=mock_conn):
        affected = upsert_market_stats("postgresql://example", row)

    sql = mock_cursor.execute.call_args[0][0]
    assert "INSERT INTO swe_market_metrics" in sql
    assert "INSERT INTO us_market_metrics" not in sql
    assert affected == 1


def test_upsert_market_stats_routes_uk_market_to_uk_table() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    row = MarketRow(
        market="uk_market",
        trading_date=date(2026, 6, 6),
        momentum_mean=Decimal("0.91"),
        momentum_std=Decimal("0.04"),
    )

    with patch("db.market.psycopg2.connect", return_value=mock_conn):
        affected = upsert_market_stats("postgresql://example", row)

    sql = mock_cursor.execute.call_args[0][0]
    assert "INSERT INTO uk_market_metrics" in sql
    assert "INSERT INTO us_market_metrics" not in sql
    assert "INSERT INTO swe_market_metrics" not in sql
    assert affected == 1


def test_purge_stale_market_executes_delete() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 3
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.market.psycopg2.connect", return_value=mock_conn):
        deleted = purge_stale_market("postgresql://example", 365)

    assert mock_cursor.execute.call_count == 3
    sqls = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert "DELETE FROM us_market_metrics" in sqls[0]
    assert "DELETE FROM swe_market_metrics" in sqls[1]
    assert "DELETE FROM uk_market_metrics" in sqls[2]
    assert all("trading_date <" in sql for sql in sqls)
    mock_conn.commit.assert_called_once()
    assert deleted == 9
