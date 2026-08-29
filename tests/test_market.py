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
        raw_mean_50=Decimal("0.95"),
        raw_mean_200=Decimal("0.90"),
        raw_std_50=Decimal("0.05"),
        raw_std_200=Decimal("0.04"),
    )

    with patch("db.market.psycopg2.connect", return_value=mock_conn):
        affected = upsert_market_stats("postgresql://example", row)

    mock_cursor.execute.assert_called_once()
    sql = mock_cursor.execute.call_args[0][0]
    assert "INSERT INTO market_metrics" in sql
    assert "ON CONFLICT (market, trading_date) DO UPDATE" in sql
    values = mock_cursor.execute.call_args[0][1]
    assert values[0] == "us_market"
    assert values[1] == date(2026, 6, 6)
    assert values[3] == Decimal("0.95")
    mock_conn.commit.assert_called_once()
    assert affected == 1


def test_purge_stale_market_executes_delete() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 3
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.market.psycopg2.connect", return_value=mock_conn):
        deleted = purge_stale_market("postgresql://example", 365)

    mock_cursor.execute.assert_called_once()
    sql = mock_cursor.execute.call_args[0][0]
    assert "DELETE FROM market_metrics" in sql
    assert "trading_date <" in sql
    mock_conn.commit.assert_called_once()
    assert deleted == 3
