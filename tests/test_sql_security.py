"""Security checks for SQL placement and secrets hygiene (RFC-009)."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

JOB_SCRIPTS = (
    "fetch_sma.py",
    "seed_tickers.py",
    "backfill_sma.py",
    "backfill_market.py",
    "refresh_tickers.py",
)

SQL_MARKERS = (
    "SELECT ",
    "INSERT ",
    "UPDATE ",
    "DELETE FROM",
    "TRUNCATE ",
    "execute(",
    "executemany(",
    "execute_values(",
)

# Legacy single-set table names as whole SQL identifiers (not us_metrics etc.).
_LEGACY_TABLE_SQL = re.compile(
    r"\b(?:FROM|INTO|UPDATE|TABLE|JOIN)\s+(tickers|metrics|market_metrics)\b",
    re.IGNORECASE,
)

DB_MODULES = (
    "country.py",
    "tickers.py",
    "metrics.py",
    "market.py",
    "retention.py",
    "truncate.py",
)


def test_job_scripts_contain_no_sql() -> None:
    """RFC-009: parameterized SQL lives in db/; job scripts stay SQL-free."""
    for name in JOB_SCRIPTS:
        path = REPO_ROOT / name
        assert path.is_file(), name
        content = path.read_text(encoding="utf-8")
        for marker in SQL_MARKERS:
            assert marker not in content, f"{name} contains {marker!r}"


def test_db_live_paths_use_country_set_tables_only() -> None:
    """RFC-009: live SQL targets us_*/swe_*/uk_* — not legacy single-set tables."""
    db_dir = REPO_ROOT / "db"
    combined = ""
    for name in DB_MODULES:
        path = db_dir / name
        assert path.is_file(), name
        combined += path.read_text(encoding="utf-8")

    assert "uk_tickers" in combined
    assert "uk_metrics" in combined
    assert "uk_market_metrics" in combined
    assert _LEGACY_TABLE_SQL.search(combined) is None


def test_gitignore_excludes_env_and_secrets() -> None:
    content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in content
    assert ".env.*" in content
    assert "/secrets" in content


def test_deploy_disables_shell_xtrace_when_writing_env() -> None:
    """Avoid leaking DATABASE_URL via set -x in Actions logs."""
    content = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "set +x" in content
    assert "install -o fansboda -g fansboda -m 600" in content
