"""Tests for production VM bootstrap script (RFC-008)."""

from pathlib import Path

BOOTSTRAP_SH = (
    Path(__file__).resolve().parents[1] / "scripts" / "bootstrap-vm.sh"
)


def test_bootstrap_requires_root() -> None:
    content = BOOTSTRAP_SH.read_text(encoding="utf-8")
    assert '$(id -u)" -ne 0' in content
    assert "Run as root or with sudo" in content


def test_bootstrap_cron_runs_thursday_at_11_utc() -> None:
    content = BOOTSTRAP_SH.read_text(encoding="utf-8")
    assert 'CRON_SCHEDULE="0 11 * * 4"' in content
    assert "0 11 * * * cd" not in content


def test_bootstrap_sets_app_paths_and_user() -> None:
    content = BOOTSTRAP_SH.read_text(encoding="utf-8")
    assert 'APP_DIR="/opt/fansboda-finance"' in content
    assert 'APP_USER="fansboda"' in content
    assert 'LOG_DIR="/var/log/fansboda-finance"' in content


def test_bootstrap_cron_sources_env_and_uses_pipenv_in_project() -> None:
    content = BOOTSTRAP_SH.read_text(encoding="utf-8")
    assert "[ -f .env ]" in content
    assert ". ./.env" in content
    assert "PIPENV_VENV_IN_PROJECT=1 pipenv run python fetch_sma.py" in content


def test_bootstrap_sets_timezone_utc() -> None:
    content = BOOTSTRAP_SH.read_text(encoding="utf-8")
    assert "timedatectl set-timezone UTC" in content


def test_bootstrap_creates_log_directory_with_fansboda_ownership() -> None:
    content = BOOTSTRAP_SH.read_text(encoding="utf-8")
    assert 'mkdir -p "$LOG_DIR"' in content
    assert 'touch "$LOG_DIR/fetch_sma.log"' in content
    assert 'chown "$APP_USER:$APP_USER" "$LOG_DIR"' in content
    assert 'chown "$APP_USER:$APP_USER" "$LOG_DIR/fetch_sma.log"' in content


def test_bootstrap_installs_cron_only_when_missing() -> None:
    content = BOOTSTRAP_SH.read_text(encoding="utf-8")
    assert "grep -q 'fetch_sma.py'" in content
    assert 'crontab -u "$APP_USER"' in content
    assert "grep -v 'fetch_sma.py'" not in content


def test_bootstrap_does_not_clone_repo() -> None:
    content = BOOTSTRAP_SH.read_text(encoding="utf-8")
    assert "git clone" not in content
    assert "REPO_URL" not in content


def test_bootstrap_does_not_write_env_file() -> None:
    content = BOOTSTRAP_SH.read_text(encoding="utf-8")
    assert "printf" not in content
    assert "DATABASE_URL=" not in content
    assert "deploy (push to main)" in content


def test_bootstrap_does_not_install_app_deps() -> None:
    """OS packages may be preinstalled; Pipfile deps come from deploy (RFC-008)."""
    content = BOOTSTRAP_SH.read_text(encoding="utf-8")
    assert "apt-get install" not in content
    assert "PIPENV_VENV_IN_PROJECT=1 pipenv install" not in content
