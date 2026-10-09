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
    REPO_ROOT / "migrate_momentum_zscore.sql",
    REPO_ROOT / "migrate_week_buckets.sql",
    REPO_ROOT / "migrate_add_business_summary.sql",
    REPO_ROOT / "migrate_add_by_sector_tables.sql",
    REPO_ROOT / "migrate_add_indices_table.sql",
    REPO_ROOT / "migrate_indices_levels.sql",
    REPO_ROOT / "migrate_add_growth_columns.sql",
    REPO_ROOT / "migrate_indices_sectors.sql",
    REPO_ROOT / "migrate_drop_by_sector_tables.sql",
    REPO_ROOT / "migrate_rename_market_indices.sql",
    REPO_ROOT / "migrate_market_index_zero_z.sql",
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
    assert "us_metrics_week_start_ticker_key" in sql
    assert "swe_metrics_week_start_ticker_key" in sql
    assert "uk_metrics_week_start_ticker_key" in sql
    assert "UNIQUE (week_start, ticker)" in sql
    assert "UNIQUE (ticker, trading_date)" not in sql


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
        "momentum",
        "z_score",
        "momentum_mean",
        "momentum_std",
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
    assert "idx_us_market_metrics_trading_date" not in sql
    assert "idx_swe_market_metrics_trading_date" not in sql
    assert "idx_uk_market_metrics_trading_date" not in sql


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


def test_schema_metrics_currency_and_momentum() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    us_metrics = sql.split("CREATE TABLE IF NOT EXISTS us_market_metrics", 1)[0]
    us_metrics = us_metrics.split("CREATE TABLE IF NOT EXISTS us_metrics", 1)[1]
    assert re.search(r"\bcurrency\s+TEXT", us_metrics)
    assert re.search(r"\bcompany\s+TEXT", us_metrics)
    for column in ("momentum", "z_score"):
        assert re.search(rf"\b{column}\s+NUMERIC\(18,\s*6\)", us_metrics)
    assert "raw_50" not in us_metrics
    assert "raw_200" not in us_metrics
    assert "sector" not in us_metrics.split("CREATE INDEX")[0]
    assert "industry" not in us_metrics.split("CREATE INDEX")[0]


def test_schema_market_metrics_primary_key() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    for table in ("us_market_metrics", "swe_market_metrics", "uk_market_metrics"):
        section = sql.split(f"CREATE TABLE IF NOT EXISTS {table}", 1)[1]
        assert re.search(r"\bmarket\s+TEXT\s+NOT NULL", section)
        assert "PRIMARY KEY (market, week_start)" in section


def test_migrate_add_exchange_name() -> None:
    sql = (REPO_ROOT / "migrate_add_exchange_name.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS exchange_name TEXT" in sql
    assert "us_tickers" in sql
    assert "swe_tickers" in sql


def test_migrate_add_uk_tables() -> None:
    sql = (REPO_ROOT / "migrate_add_uk_tables.sql").read_text(encoding="utf-8")
    for table in ("uk_tickers", "uk_metrics", "uk_market_metrics"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "gb_market" in sql
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


def test_migrate_momentum_zscore() -> None:
    sql = (REPO_ROOT / "migrate_momentum_zscore.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS momentum" in sql
    assert "ADD COLUMN IF NOT EXISTS z_score" in sql
    assert "ADD COLUMN IF NOT EXISTS momentum_mean" in sql
    assert "ADD COLUMN IF NOT EXISTS momentum_std" in sql
    assert "DROP COLUMN IF EXISTS raw_50" in sql
    assert "DROP COLUMN IF EXISTS raw_mean_50" in sql
    for table in ("us_metrics", "swe_metrics", "uk_metrics"):
        assert table in sql
    for table in ("us_market_metrics", "swe_market_metrics", "uk_market_metrics"):
        assert table in sql


def test_apply_migrations_skips_steps_11_to_14_once_raw_ratios_are_gone() -> None:
    script = APPLY_MIGRATIONS_SH.read_text(encoding="utf-8")
    assert "column_name = 'raw_50'" in script
    skip_block = script.split('"$has_raw_ratios" == "no"', 1)[1].split("fi\n", 1)[0]
    assert "migrate_week_buckets.sql" in skip_block
    assert "exit 0" in skip_block
    assert script.index('"$has_raw_ratios" == "no"') < script.index(
        "migrate_split_us_swe_tables.sql"
    )


def test_schema_tickers_have_business_summary() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    for table in ("us_tickers", "swe_tickers", "uk_tickers"):
        section = sql.split(f"CREATE TABLE IF NOT EXISTS {table}", 1)[1].split(");", 1)[0]
        assert re.search(r"\bbusiness_summary\s+TEXT", section), table


def test_migrate_add_business_summary() -> None:
    sql = (REPO_ROOT / "migrate_add_business_summary.sql").read_text(encoding="utf-8")
    for table in ("us_tickers", "swe_tickers", "uk_tickers"):
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS business_summary TEXT" in sql


def test_apply_migrations_runs_business_summary_after_week_buckets() -> None:
    script = APPLY_MIGRATIONS_SH.read_text(encoding="utf-8")
    skip_block = script.split('"$has_raw_ratios" == "no"', 1)[1].split("fi\n", 1)[0]
    assert skip_block.index("migrate_week_buckets.sql") < skip_block.index(
        "migrate_add_business_summary.sql"
    )
    assert script.rindex("migrate_add_business_summary.sql") > script.rindex(
        "migrate_week_buckets.sql"
    )


def test_migrate_week_buckets() -> None:
    sql = (REPO_ROOT / "migrate_week_buckets.sql").read_text(encoding="utf-8")
    assert "ARRAY['us', 'swe', 'uk']" in sql
    assert "ADD COLUMN week_start DATE" in sql
    assert "date_trunc(''week'', trading_date)::date" in sql
    assert "older.trading_date < newer.trading_date" in sql
    assert "ALTER COLUMN week_start SET NOT NULL" in sql
    assert "_metrics_ticker_trading_date_key" in sql
    assert "UNIQUE (week_start, ticker)" in sql
    assert "_metrics_week_start_ticker_key" in sql
    assert "PRIMARY KEY (market, week_start)" in sql
    assert "column_name = 'week_start'" in sql
    assert "column_name = 'trading_date'" in sql


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
    assert script.index("migrate_momentum_zscore.sql") > script.index(
        "migrate_add_uk_tables.sql"
    )
    assert script.rindex("migrate_week_buckets.sql") > script.index(
        "migrate_momentum_zscore.sql"
    )
    assert "migrate_one_row_per_ticker.sql" not in script.split("LEGACY_MIGRATIONS=", 1)[
        1
    ].split(")", 1)[0]
    assert "migrate_add_tickers_table.sql" not in script.split("LEGACY_MIGRATIONS=", 1)[
        1
    ].split(")", 1)[0]


BY_SECTOR_TABLES = ("us_by_sector", "swe_by_sector", "uk_by_sector")
BY_SECTOR_COLUMNS = (
    r"\bsector\s+TEXT\s+NOT NULL",
    r"\bweek_start\s+DATE\s+NOT NULL",
    r"\bupdated_at\s+TIMESTAMPTZ\s+NOT NULL",
    r"\bticker_count\s+INTEGER\s+NOT NULL",
    r"\bmomentum_mean\s+NUMERIC\(18, 6\)",
    r"\bmomentum_median\s+NUMERIC\(18, 6\)",
    r"\bz_score_mean\s+NUMERIC\(18, 6\)",
    r"\bpct_uptrend\s+NUMERIC\(18, 6\)",
    r"PRIMARY KEY \(sector, week_start\)",
)


def test_step_17_defines_by_sector_tables_and_schema_omits_them() -> None:
    schema = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "by_sector" not in schema
    for path in (REPO_ROOT / "migrate_add_by_sector_tables.sql",):
        sql = path.read_text(encoding="utf-8")
        for table in BY_SECTOR_TABLES:
            section = sql.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split(
                ");", 1
            )[0]
            for pattern in BY_SECTOR_COLUMNS:
                assert re.search(pattern, section), (path.name, table, pattern)


def test_apply_migrations_runs_by_sector_last_in_both_paths() -> None:
    script = APPLY_MIGRATIONS_SH.read_text(encoding="utf-8")
    skip_block = script.split('"$has_raw_ratios" == "no"', 1)[1].split("fi\n", 1)[0]
    assert skip_block.index("migrate_add_business_summary.sql") < skip_block.index(
        "migrate_add_by_sector_tables.sql"
    )
    assert script.rindex("migrate_add_by_sector_tables.sql") > script.rindex(
        "migrate_add_business_summary.sql"
    )


INDICES_COLUMNS = (
    r"\bticker\s+TEXT\s+NOT NULL",
    r"\bname\s+TEXT\s+NOT NULL",
    r"\bcountry\s+TEXT\s+NOT NULL",
    r"\btrading_date\s+DATE\s+NOT NULL",
    r"\bupdated_at\s+TIMESTAMPTZ\s+NOT NULL",
    r"\bticker_count\s+INTEGER\s+NOT NULL",
    r"\bcurrent_price\s+NUMERIC\(18, 6\)\s+NOT NULL",
    r"\bsma_50\s+NUMERIC\(18, 6\)\s+NOT NULL",
    r"\bsma_200\s+NUMERIC\(18, 6\)\s+NOT NULL",
    r"\bmomentum\s+NUMERIC\(18, 6\)",
    r"PRIMARY KEY \(ticker, trading_date\)",
)


def _indices_ddl(path) -> str:
    sql = path.read_text(encoding="utf-8")
    return sql.split("CREATE TABLE IF NOT EXISTS indices (", 1)[1].split(");", 1)[0]


def test_schema_and_step_19_define_indices_v2() -> None:
    for path in (SCHEMA_SQL, REPO_ROOT / "migrate_indices_levels.sql"):
        section = _indices_ddl(path)
        for pattern in INDICES_COLUMNS:
            if path == SCHEMA_SQL and "name" in pattern:
                assert not re.search(pattern, section), "name merged into sector"
                continue
            assert re.search(pattern, section), (path.name, pattern)
        assert "week_start" not in section
        assert "index_price" not in section


def test_step_19_only_drops_v1_indices() -> None:
    sql = " ".join(
        (REPO_ROOT / "migrate_indices_levels.sql").read_text(encoding="utf-8").split()
    )
    guard = sql.index("column_name = 'week_start'")
    assert guard < sql.index("DROP TABLE indices;")
    assert sql.index("DROP TABLE indices;") < sql.index(
        "CREATE TABLE IF NOT EXISTS indices"
    )


def test_apply_migrations_runs_indices_steps_in_order_in_both_paths() -> None:
    script = APPLY_MIGRATIONS_SH.read_text(encoding="utf-8")
    skip_block = script.split('"$has_raw_ratios" == "no"', 1)[1].split("fi\n", 1)[0]
    assert (
        skip_block.index("migrate_add_by_sector_tables.sql")
        < skip_block.index("migrate_add_indices_table.sql")
        < skip_block.index("migrate_indices_levels.sql")
    )
    assert (
        script.rindex("migrate_add_by_sector_tables.sql")
        < script.rindex("migrate_add_indices_table.sql")
        < script.rindex("migrate_indices_levels.sql")
    )


GROWTH_COLUMNS = ("price_growth", "sma_50_growth", "sma_200_growth")


def test_schema_metrics_have_growth_columns() -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    for prefix in ("us", "swe", "uk"):
        section = sql.split(f"CREATE TABLE IF NOT EXISTS {prefix}_metrics (", 1)[
            1
        ].split(");", 1)[0]
        for column in GROWTH_COLUMNS:
            assert re.search(rf"\b{column}\s+NUMERIC\(18, 6\)", section), (
                prefix,
                column,
            )


def test_step_20_adds_growth_columns_idempotently() -> None:
    sql = " ".join(
        (REPO_ROOT / "migrate_add_growth_columns.sql").read_text(encoding="utf-8").split()
    )
    for prefix in ("us", "swe", "uk"):
        assert f"ALTER TABLE {prefix}_metrics" in sql
    for column in GROWTH_COLUMNS:
        assert sql.count(f"ADD COLUMN IF NOT EXISTS {column} NUMERIC(18, 6)") == 3
    assert "DROP" not in sql


def test_apply_migrations_runs_step_20_after_indices_levels_in_both_paths() -> None:
    script = APPLY_MIGRATIONS_SH.read_text(encoding="utf-8")
    skip_block = script.split('"$has_raw_ratios" == "no"', 1)[1].split("fi\n", 1)[0]
    assert skip_block.index("migrate_indices_levels.sql") < skip_block.index(
        "migrate_add_growth_columns.sql"
    )
    assert script.rindex("migrate_indices_levels.sql") < script.rindex(
        "migrate_add_growth_columns.sql"
    )


SECTOR_INDEX_COLUMNS = (
    r"\bsector\s+TEXT\s+NOT NULL",
    r"\bcurrency\s+TEXT",
    r"\bpct_uptrend\s+NUMERIC\(18, 6\)",
    r"\bz_score\s+NUMERIC\(18, 6\)",
)


def test_schema_indices_have_sector_columns() -> None:
    section = _indices_ddl(SCHEMA_SQL)
    for pattern in SECTOR_INDEX_COLUMNS:
        assert re.search(pattern, section), pattern
    assert "idx_indices_country_trading_date" in SCHEMA_SQL.read_text(encoding="utf-8")


def test_step_21_rebuilds_indices_with_sector_second() -> None:
    sql = " ".join(
        (REPO_ROOT / "migrate_indices_sectors.sql").read_text(encoding="utf-8").split()
    )
    guard = sql.index("column_name = 'sector' AND ordinal_position = 2")
    for column, kind in (
        ("sector", "TEXT"),
        ("currency", "TEXT"),
        ("pct_uptrend", "NUMERIC(18, 6)"),
        ("z_score", "NUMERIC(18, 6)"),
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column} {kind}" in sql
    copy_name = sql.index("EXECUTE 'UPDATE indices SET sector = name'")
    assert sql.index("column_name = 'name'") < copy_name
    new_table = sql.split("CREATE TABLE indices_new (", 1)[1].split(");", 1)[0]
    columns = [part.strip().split()[0] for part in new_table.split(",") if part.strip()]
    assert columns[:2] == ["ticker", "sector"]
    assert "name" not in columns
    assert re.search(r"\bsector\s+TEXT\s+NOT NULL", new_table)
    order = [
        guard,
        copy_name,
        sql.index("CREATE TABLE indices_new"),
        sql.index("INSERT INTO indices_new"),
        sql.index("DROP TABLE indices;"),
        sql.index("ALTER TABLE indices_new RENAME TO indices;"),
        sql.index("RENAME CONSTRAINT indices_new_pkey TO indices_pkey"),
        sql.index("CREATE INDEX IF NOT EXISTS idx_indices_country_trading_date"),
    ]
    assert order == sorted(order)
    assert "DROP TABLE IF EXISTS" not in sql


def test_schema_indices_sector_is_second_column() -> None:
    section = _indices_ddl(SCHEMA_SQL)
    columns = [line.split()[0] for line in section.splitlines() if line.strip()]
    assert columns[:3] == ["ticker", "sector", "country"]


def test_step_22_drops_only_by_sector_tables() -> None:
    sql = (REPO_ROOT / "migrate_drop_by_sector_tables.sql").read_text(encoding="utf-8")
    statements = [
        line.strip()
        for line in sql.splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    assert statements == [
        "DROP TABLE IF EXISTS us_by_sector;",
        "DROP TABLE IF EXISTS swe_by_sector;",
        "DROP TABLE IF EXISTS uk_by_sector;",
    ]


def test_apply_migrations_runs_steps_21_22_last_in_both_paths() -> None:
    script = APPLY_MIGRATIONS_SH.read_text(encoding="utf-8")
    skip_block = script.split('"$has_raw_ratios" == "no"', 1)[1].split("fi\n", 1)[0]
    for find in (skip_block.index, script.rindex):
        assert (
            find("migrate_add_by_sector_tables.sql")
            < find("migrate_add_growth_columns.sql")
            < find("migrate_indices_sectors.sql")
            < find("migrate_drop_by_sector_tables.sql")
        )


STEP_23_SQL = REPO_ROOT / "migrate_rename_market_indices.sql"


def _sql_statements(path: Path) -> str:
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("--")
    ]
    return " ".join(" ".join(lines).split())


def test_step_23_relabels_only_market_tickers() -> None:
    sql = _sql_statements(STEP_23_SQL)
    for keyword in ("CREATE", "ALTER", "DROP", "TRUNCATE", "DELETE", "LIKE"):
        assert keyword not in sql.upper()
    assert "UPDATE indices" in sql
    assert "i.ticker = v.ticker" in sql
    assert "IS DISTINCT FROM v.label" in sql
    for ticker in ("'US-IDX'", "'SWE-IDX'", "'UK-IDX'"):
        assert ticker in sql


def test_step_23_labels_match_index_definitions() -> None:
    from equity_index import INDEX_DEFINITIONS

    sql = _sql_statements(STEP_23_SQL)
    for definition in INDEX_DEFINITIONS.values():
        assert f"('{definition.ticker}', '{definition.name}')" in sql


def test_apply_migrations_runs_step_23_after_step_22_in_both_paths() -> None:
    script = APPLY_MIGRATIONS_SH.read_text(encoding="utf-8")
    skip_block = script.split('"$has_raw_ratios" == "no"', 1)[1].split("fi\n", 1)[0]
    for find in (skip_block.index, script.rindex):
        assert find("migrate_drop_by_sector_tables.sql") < find(
            "migrate_rename_market_indices.sql"
        )


STEP_24_SQL = REPO_ROOT / "migrate_market_index_zero_z.sql"


def test_step_24_zeroes_only_market_index_z_scores() -> None:
    sql = _sql_statements(STEP_24_SQL)
    for keyword in ("CREATE", "ALTER", "DROP", "TRUNCATE", "DELETE", "LIKE"):
        assert keyword not in sql.upper()
    assert "UPDATE indices" in sql
    assert "SET z_score = 0" in sql
    assert "ticker IN ('US-IDX', 'SWE-IDX', 'UK-IDX')" in sql
    assert "z_score IS DISTINCT FROM 0" in sql


def test_step_24_tickers_match_index_definitions() -> None:
    from equity_index import INDEX_DEFINITIONS

    sql = _sql_statements(STEP_24_SQL)
    for definition in INDEX_DEFINITIONS.values():
        assert f"'{definition.ticker}'" in sql


def test_apply_migrations_runs_step_24_after_step_23_in_both_paths() -> None:
    script = APPLY_MIGRATIONS_SH.read_text(encoding="utf-8")
    skip_block = script.split('"$has_raw_ratios" == "no"', 1)[1].split("fi\n", 1)[0]
    for find in (skip_block.index, script.rindex):
        assert find("migrate_rename_market_indices.sql") < find(
            "migrate_market_index_zero_z.sql"
        )
