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
    REPO_ROOT / "migrate_rename_name_to_company.sql",
    REPO_ROOT / "migrate_add_raw_ratios_and_market.sql",
    REPO_ROOT / "migrate_tickers_market_and_market_metrics.sql",
]
APPLY_MIGRATIONS_SH = REPO_ROOT / "scripts" / "apply_migrations.sh"


@pytest.mark.parametrize("path", [SCHEMA_SQL, *MIGRATIONS])
def test_sql_file_exists(path: Path) -> None:
    assert path.is_file(), f"missing {path.name}"


def test_schema_defines_tickers_metrics_and_market_metrics() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS tickers" in sql
    assert "CREATE TABLE IF NOT EXISTS metrics" in sql
    assert "CREATE TABLE IF NOT EXISTS market_metrics" in sql


def test_schema_enforces_history_unique_constraint() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "metrics_ticker_trading_date_key" in sql
    assert "UNIQUE (ticker, trading_date)" in sql


def test_schema_cascade_delete_from_tickers() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "REFERENCES tickers (symbol) ON DELETE CASCADE" in sql


def test_schema_numeric_precision() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    for column in (
        "sma_50",
        "sma_200",
        "current_price",
        "raw_50",
        "raw_200",
        "raw_mean_50",
        "raw_std_200",
    ):
        assert re.search(rf"\b{column}\s+NUMERIC\(18,\s*6\)", sql)


def test_schema_retention_index() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "idx_metrics_trading_date" in sql
    assert "ON metrics (trading_date)" in sql
    assert "idx_market_metrics_trading_date" in sql
    assert "ON market_metrics (trading_date)" in sql


def test_schema_tickers_updated_at() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert re.search(r"\bupdated_at\s+TIMESTAMPTZ\s+NOT NULL", sql.split("metrics")[0])


def test_schema_tickers_sector_industry_columns() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    tickers_section = sql.split("CREATE TABLE IF NOT EXISTS metrics", 1)[0]
    for column in ("sector", "industry"):
        assert re.search(rf"\b{column}\s+TEXT", tickers_section)


def test_schema_tickers_market_column() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    tickers_section = sql.split("CREATE TABLE IF NOT EXISTS metrics", 1)[0]
    assert re.search(r"\bmarket\s+TEXT", tickers_section)


def test_schema_metrics_currency_column() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    metrics_section = sql.split("CREATE TABLE IF NOT EXISTS metrics", 1)[1]
    assert re.search(r"\bcurrency\s+TEXT", metrics_section)
    assert re.search(r"\bcompany\s+TEXT", metrics_section)
    assert "sector" not in metrics_section.split("CREATE INDEX")[0]
    assert "industry" not in metrics_section.split("CREATE INDEX")[0]


def test_schema_tickers_company_column() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    tickers_section = sql.split("CREATE TABLE IF NOT EXISTS metrics", 1)[0]
    assert re.search(r"\bcompany\s+TEXT", tickers_section)
    assert not re.search(r"\bname\s+TEXT", tickers_section)


def test_schema_metrics_raw_ratio_columns() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    metrics_section = sql.split("CREATE TABLE IF NOT EXISTS market_metrics", 1)[0]
    for column in ("raw_50", "raw_200"):
        assert re.search(rf"\b{column}\s+NUMERIC\(18,\s*6\)", metrics_section)


def test_schema_market_metrics_primary_key() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    market_section = sql.split("CREATE TABLE IF NOT EXISTS market_metrics", 1)[1]
    assert re.search(r"\bmarket\s+TEXT\s+NOT NULL", market_section)
    assert "PRIMARY KEY (market, trading_date)" in market_section


def test_migrate_add_raw_ratios_and_market() -> None:
    sql = (REPO_ROOT / "migrate_add_raw_ratios_and_market.sql").read_text(
        encoding="utf-8"
    )
    assert "ADD COLUMN IF NOT EXISTS raw_50" in sql
    assert "ADD COLUMN IF NOT EXISTS raw_200" in sql
    assert "CREATE TABLE IF NOT EXISTS market" in sql
    assert "raw_mean_50" in sql
    assert "raw_std_200" in sql


def test_migrate_tickers_market_and_market_metrics() -> None:
    sql = (
        REPO_ROOT / "migrate_tickers_market_and_market_metrics.sql"
    ).read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS market TEXT" in sql
    assert "CREATE TABLE IF NOT EXISTS market_metrics" in sql
    assert "PRIMARY KEY (market, trading_date)" in sql
    assert "DROP TABLE IF EXISTS market" in sql
    assert "idx_market_metrics_trading_date" in sql


def test_migrate_move_metadata_to_tickers() -> None:
    sql = (REPO_ROOT / "migrate_move_metadata_to_tickers.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS sector TEXT" in sql
    assert "ADD COLUMN IF NOT EXISTS industry TEXT" in sql
    assert "ADD COLUMN IF NOT EXISTS currency TEXT" in sql
    assert "DROP COLUMN IF EXISTS sector" in sql
    assert "DROP COLUMN IF EXISTS industry" in sql


def test_migrate_rename_name_to_company() -> None:
    sql = (REPO_ROOT / "migrate_rename_name_to_company.sql").read_text(encoding="utf-8")
    assert "RENAME COLUMN name TO company" in sql
    assert "tickers" in sql
    assert "metrics" in sql


def test_migrate_metrics_history_restores_composite_unique() -> None:
    sql = (REPO_ROOT / "migrate_metrics_history.sql").read_text(encoding="utf-8")
    assert "DROP CONSTRAINT IF EXISTS metrics_ticker_key" in sql
    assert "metrics_ticker_trading_date_key" in sql


def test_apply_migrations_script_lists_ci_safe_migrations_in_order() -> None:
    script = APPLY_MIGRATIONS_SH.read_text(encoding="utf-8")
    ci_safe = [
        "migrate_add_current_price.sql",
        "migrate_metrics_history.sql",
        "migrate_add_trading_date_index.sql",
        "migrate_add_tickers_updated_at.sql",
        "migrate_move_metadata_to_tickers.sql",
        "migrate_rename_name_to_company.sql",
        "migrate_add_raw_ratios_and_market.sql",
        "migrate_tickers_market_and_market_metrics.sql",
    ]
    for name in ci_safe:
        assert name in script
    positions = [script.index(name) for name in ci_safe]
    assert positions == sorted(positions)
    migrations_block = script.split("MIGRATIONS=(", 1)[1].split(")", 1)[0]
    assert "migrate_one_row_per_ticker.sql" not in migrations_block
    assert "migrate_add_tickers_table.sql" not in migrations_block
