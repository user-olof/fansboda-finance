"""Tests for ephemeral dev VM bootstrap script (RFC-011)."""

from pathlib import Path

BOOTSTRAP_DEV_SH = (
    Path(__file__).resolve().parents[1] / "scripts" / "bootstrap-dev-vm.sh"
)


def test_bootstrap_dev_sets_app_paths_and_user() -> None:
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert 'APP_DIR="/opt/fansboda-finance"' in content
    assert 'APP_USER="fansboda"' in content


def test_bootstrap_dev_writes_ready_marker() -> None:
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert 'BOOTSTRAP_MARKER="/var/run/fansboda-dev-bootstrap.done"' in content
    assert 'touch "$BOOTSTRAP_MARKER"' in content


def test_bootstrap_dev_does_not_clone_repo() -> None:
    """Code is copied from the CI checkout, not cloned on the VM."""
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert "git clone" not in content
    assert "metadata_attr" not in content


def test_bootstrap_dev_does_not_install_python_deps() -> None:
    """pipenv install runs in the deploy job after the code is copied over."""
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert "pipenv install --deploy" not in content


def test_bootstrap_dev_does_not_install_cron() -> None:
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert "crontab" not in content
    assert "fetch_sma.py" not in content


def test_bootstrap_dev_does_not_write_env_file() -> None:
    content = BOOTSTRAP_DEV_SH.read_text(encoding="utf-8")
    assert "DATABASE_URL=" not in content
    assert "dev-backfill CI" in content
