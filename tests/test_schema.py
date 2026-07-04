import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = REPO_ROOT / "schema.sql"
MIGRATIONS = [
    REPO_ROOT / "migrate_add_current_price.sql",
    REPO_ROOT / "migrate_one_row_per_ticker.sql",
    REPO_ROOT / "migrate_add_tickers_table.sql",
    REPO_ROOT / "migrate_metrics_history.sql",
    REPO_ROOT / "migrate_add_trading_date_index.sql",
    REPO_ROOT / "migrate_add_tickers_updated_at.sql",
    REPO_ROOT / "migrate_move_metadata_to_tickers.sql",
]


@pytest.mark.parametrize("path", [SCHEMA_SQL, *MIGRATIONS])
def test_sql_file_exists(path: Path) -> None:
    assert path.is_file(), f"missing {path.name}"


def test_schema_defines_tickers_and_metrics() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS tickers" in sql
    assert "CREATE TABLE IF NOT EXISTS metrics" in sql


def test_schema_enforces_history_unique_constraint() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "metrics_ticker_trading_date_key" in sql
    assert "UNIQUE (ticker, trading_date)" in sql


def test_schema_cascade_delete_from_tickers() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "REFERENCES tickers (symbol) ON DELETE CASCADE" in sql


def test_schema_numeric_precision() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    for column in ("sma_50", "sma_200", "current_price"):
        assert re.search(rf"\b{column}\s+NUMERIC\(18,\s*6\)", sql)


def test_schema_retention_index() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "idx_metrics_trading_date" in sql
    assert "ON metrics (trading_date)" in sql


def test_schema_tickers_updated_at() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert re.search(r"\bupdated_at\s+TIMESTAMPTZ\s+NOT NULL", sql.split("metrics")[0])


def test_schema_tickers_sector_industry_columns() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    tickers_section = sql.split("CREATE TABLE IF NOT EXISTS metrics", 1)[0]
    for column in ("sector", "industry"):
        assert re.search(rf"\b{column}\s+TEXT", tickers_section)


def test_schema_metrics_currency_column() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    metrics_section = sql.split("CREATE TABLE IF NOT EXISTS metrics", 1)[1]
    assert re.search(r"\bcurrency\s+TEXT", metrics_section)
    assert "sector" not in metrics_section.split("CREATE INDEX")[0]
    assert "industry" not in metrics_section.split("CREATE INDEX")[0]


def test_migrate_move_metadata_to_tickers() -> None:
    sql = (REPO_ROOT / "migrate_move_metadata_to_tickers.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS sector TEXT" in sql
    assert "ADD COLUMN IF NOT EXISTS industry TEXT" in sql
    assert "ADD COLUMN IF NOT EXISTS currency TEXT" in sql
    assert "DROP COLUMN IF EXISTS sector" in sql
    assert "DROP COLUMN IF EXISTS industry" in sql


def test_migrate_metrics_history_restores_composite_unique() -> None:
    sql = (REPO_ROOT / "migrate_metrics_history.sql").read_text(encoding="utf-8")
    assert "DROP CONSTRAINT IF EXISTS metrics_ticker_key" in sql
    assert "metrics_ticker_trading_date_key" in sql
