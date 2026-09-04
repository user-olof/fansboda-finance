"""Security checks for SQL placement and secrets hygiene (RFC-009)."""

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


def test_job_scripts_contain_no_sql() -> None:
    """RFC-009: parameterized SQL lives in db/; job scripts stay SQL-free."""
    for name in JOB_SCRIPTS:
        path = REPO_ROOT / name
        assert path.is_file(), name
        content = path.read_text(encoding="utf-8")
        for marker in SQL_MARKERS:
            assert marker not in content, f"{name} contains {marker!r}"


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
