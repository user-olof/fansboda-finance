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
    REPO_ROOT / "migrate_split_us_swe_tables.sql",
    REPO_ROOT / "migrate_add_exchange_name.sql",
    REPO_ROOT / "migrate_add_uk_tables.sql",
]
APPLY_MIGRATIONS_SH = REPO_ROOT / "scripts" / "apply_migrations.sh"
COUNTRY_TABLES = (
    "us_tickers",
    "us_metrics",
    "us_market_metrics",
    "swe_tickers",
    "swe_metrics",
    "swe_market_metrics",
    "uk_tickers",
    "uk_metrics",
    "uk_market_metrics",
)
US_SWE_TABLES = (
    "us_tickers",
    "us_metrics",
    "us_market_metrics",
    "swe_tickers",
    "swe_metrics",
    "swe_market_metrics",
)


@pytest.mark.parametrize("path", [SCHEMA_SQL, *MIGRATIONS])
def test_sql_file_exists(path: Path) -> None:
    assert path.is_file(), f"missing {path.name}"


def test_schema_defines_country_table_sets() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    for table in COUNTRY_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "CREATE TABLE IF NOT EXISTS tickers" not in sql
    assert "CREATE TABLE IF NOT EXISTS metrics" not in sql
    assert "CREATE TABLE IF NOT EXISTS market_metrics" not in sql


def test_schema_enforces_history_unique_constraint() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "us_metrics_ticker_trading_date_key" in sql
    assert "swe_metrics_ticker_trading_date_key" in sql
    assert "uk_metrics_ticker_trading_date_key" in sql
    assert "UNIQUE (ticker, trading_date)" in sql


def test_schema_cascade_delete_from_tickers() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "REFERENCES us_tickers (symbol) ON DELETE CASCADE" in sql
    assert "REFERENCES swe_tickers (symbol) ON DELETE CASCADE" in sql
    assert "REFERENCES uk_tickers (symbol) ON DELETE CASCADE" in sql


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


def test_schema_retention_indexes() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "idx_us_metrics_trading_date" in sql
    assert "ON us_metrics (trading_date)" in sql
    assert "idx_swe_metrics_trading_date" in sql
    assert "ON swe_metrics (trading_date)" in sql
    assert "idx_uk_metrics_trading_date" in sql
    assert "ON uk_metrics (trading_date)" in sql
    assert "idx_us_market_metrics_trading_date" in sql
    assert "idx_swe_market_metrics_trading_date" in sql
    assert "idx_uk_market_metrics_trading_date" in sql


def test_schema_tickers_updated_at() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    us_tickers = sql.split("CREATE TABLE IF NOT EXISTS us_metrics", 1)[0]
    assert re.search(r"\bupdated_at\s+TIMESTAMPTZ\s+NOT NULL", us_tickers)


def test_schema_tickers_sector_industry_market_company_exchange_name() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    us_tickers = sql.split("CREATE TABLE IF NOT EXISTS us_metrics", 1)[0]
    for column in ("sector", "industry", "market", "company", "exchange_name"):
        assert re.search(rf"\b{column}\s+TEXT", us_tickers)
    assert not re.search(r"\bname\s+TEXT", us_tickers)


def test_schema_metrics_currency_and_raw_ratios() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    us_metrics = sql.split("CREATE TABLE IF NOT EXISTS us_market_metrics", 1)[0]
    us_metrics = us_metrics.split("CREATE TABLE IF NOT EXISTS us_metrics", 1)[1]
    assert re.search(r"\bcurrency\s+TEXT", us_metrics)
    assert re.search(r"\bcompany\s+TEXT", us_metrics)
    for column in ("raw_50", "raw_200"):
        assert re.search(rf"\b{column}\s+NUMERIC\(18,\s*6\)", us_metrics)
    assert "sector" not in us_metrics.split("CREATE INDEX")[0]
    assert "industry" not in us_metrics.split("CREATE INDEX")[0]


def test_schema_market_metrics_primary_key() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    for table in ("us_market_metrics", "swe_market_metrics", "uk_market_metrics"):
        section = sql.split(f"CREATE TABLE IF NOT EXISTS {table}", 1)[1]
        assert re.search(r"\bmarket\s+TEXT\s+NOT NULL", section)
        assert "PRIMARY KEY (market, trading_date)" in section


def test_migrate_add_exchange_name() -> None:
    sql = (REPO_ROOT / "migrate_add_exchange_name.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS exchange_name TEXT" in sql
    assert "us_tickers" in sql
    assert "swe_tickers" in sql


def test_migrate_add_uk_tables() -> None:
    sql = (REPO_ROOT / "migrate_add_uk_tables.sql").read_text(encoding="utf-8")
    for table in ("uk_tickers", "uk_metrics", "uk_market_metrics"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "uk_market" in sql
    assert "%.L" in sql
    assert "exchange_name" in sql


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


def test_migrate_split_us_swe_tables() -> None:
    sql = (REPO_ROOT / "migrate_split_us_swe_tables.sql").read_text(encoding="utf-8")
    for table in US_SWE_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "DROP TABLE IF EXISTS metrics CASCADE" in sql
    assert "DROP TABLE IF EXISTS market_metrics CASCADE" in sql
    assert "DROP TABLE IF EXISTS tickers CASCADE" in sql
    assert "se_market" in sql
    assert "%.ST" in sql


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
    assert "schema.sql" in script
    assert "migrate_split_us_swe_tables.sql" in script
    assert "to_regclass('public.metrics')" in script
    assert "to_regclass('public.tickers')" in script
    legacy = [
        "migrate_add_current_price.sql",
        "migrate_metrics_history.sql",
        "migrate_add_trading_date_index.sql",
        "migrate_add_tickers_updated_at.sql",
        "migrate_move_metadata_to_tickers.sql",
        "migrate_rename_name_to_company.sql",
        "migrate_add_raw_ratios_and_market.sql",
        "migrate_tickers_market_and_market_metrics.sql",
    ]
    for name in legacy:
        assert name in script
    positions = [script.index(name) for name in legacy]
    assert positions == sorted(positions)
    assert script.index("schema.sql") < script.index("LEGACY_MIGRATIONS=")
    assert script.index("migrate_split_us_swe_tables.sql") > script.index(
        "LEGACY_MIGRATIONS="
    )
    assert script.index("migrate_add_exchange_name.sql") > script.index(
        "migrate_split_us_swe_tables.sql"
    )
    assert script.index("migrate_add_uk_tables.sql") > script.index(
        "migrate_add_exchange_name.sql"
    )
    assert "migrate_one_row_per_ticker.sql" not in script.split("LEGACY_MIGRATIONS=", 1)[
        1
    ].split(")", 1)[0]
    assert "migrate_add_tickers_table.sql" not in script.split("LEGACY_MIGRATIONS=", 1)[
        1
    ].split(")", 1)[0]
