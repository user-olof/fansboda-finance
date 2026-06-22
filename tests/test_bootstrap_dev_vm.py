"""Tests for ephemeral dev VM bootstrap script (RFC-011)."""

from pathlib import Path

BOOTSTRAP_DEV_SH = (
    Path(__file__).resolve().parents[1] / "scripts" / "bootstrap-dev-vm.sh"
)


def test_bootstrap_dev_sets_app_paths_and_user() -> None:
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert 'APP_DIR="/opt/fansboda-finance"' in content
    assert 'APP_USER="fansboda"' in content


def test_bootstrap_dev_reads_repo_metadata() -> None:
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert "metadata_attr repo-url" in content
    assert "metadata_attr branch" in content
    assert 'git clone --branch "$BRANCH"' in content


def test_bootstrap_dev_installs_dependencies_as_fansboda() -> None:
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert "PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy" in content
    assert 'su -s /bin/bash "$APP_USER"' in content


def test_bootstrap_dev_does_not_install_cron() -> None:
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert "crontab" not in content
    assert "fetch_sma.py" not in content


def test_bootstrap_dev_does_not_write_env_file() -> None:
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert "DATABASE_URL=" not in content
    assert "dev-backfill CI" in content
