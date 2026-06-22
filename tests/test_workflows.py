"""CI checks for GitHub Actions workflows (RFC-007, RFC-009, RFC-011)."""

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
TEST_YML = WORKFLOWS / "test.yml"
DEPLOY_YML = WORKFLOWS / "deploy.yml"
DEV_BACKFILL_YML = WORKFLOWS / "dev-backfill.yml"


def test_test_workflow_runs_on_main_only() -> None:
    content = TEST_YML.read_text(encoding="utf-8")
    assert content.count("branches: [main]") == 2
    assert "branches: [main, dev]" not in content
    assert "pipenv run pytest" in content


def test_test_workflow_uses_python_311() -> None:
    content = TEST_YML.read_text(encoding="utf-8")
    assert 'python-version: "3.11"' in content


def test_deploy_workflow_runs_on_main_push_only() -> None:
    content = DEPLOY_YML.read_text(encoding="utf-8")
    assert "branches: [main]" in content
    assert "environment: production" in content


def test_deploy_workflow_uses_workload_identity_federation() -> None:
    content = DEPLOY_YML.read_text(encoding="utf-8")
    assert "workload_identity_provider:" in content
    assert "GCP_WORKLOAD_IDENTITY_PROVIDER" in content
    assert "GCP_DEPLOY_SERVICE_ACCOUNT" in content


def test_deploy_workflow_does_not_use_json_key() -> None:
    content = DEPLOY_YML.read_text(encoding="utf-8")
    assert "credentials_json" not in content
    assert "GCP_SA_KEY" not in content


def test_deploy_workflow_requests_oidc_token() -> None:
    content = DEPLOY_YML.read_text(encoding="utf-8")
    assert "id-token: write" in content


def test_deploy_workflow_writes_production_env() -> None:
    content = DEPLOY_YML.read_text(encoding="utf-8")
    assert "APP_ENV=production" in content
    assert "chown fansboda:fansboda" in content
    assert "chmod 600" in content


def test_deploy_workflow_targets_production_vm_paths() -> None:
    """RFC-008: deploy updates /opt/fansboda-finance as fansboda."""
    content = DEPLOY_YML.read_text(encoding="utf-8")
    assert "/opt/fansboda-finance" in content
    assert "sudo -u fansboda" in content
    assert "git pull origin main" in content
    assert "DATABASE_URL=" in content


def test_dev_backfill_workflow_runs_on_dev_push_only() -> None:
    content = DEV_BACKFILL_YML.read_text(encoding="utf-8")
    assert "branches: [dev]" in content
    assert "environment: development" in content
    assert "branches: [main]" not in content


def test_dev_backfill_workflow_creates_ephemeral_vm() -> None:
    content = DEV_BACKFILL_YML.read_text(encoding="utf-8")
    assert "data-fetcher-dev" in content
    assert "gcloud compute instances create" in content
    assert "gcloud compute instances delete" in content


def test_dev_backfill_workflow_uses_workload_identity_federation() -> None:
    content = DEV_BACKFILL_YML.read_text(encoding="utf-8")
    assert "workload_identity_provider:" in content
    assert "GCP_WORKLOAD_IDENTITY_PROVIDER" in content
    assert "GCP_DEPLOY_SERVICE_ACCOUNT" in content
    assert "credentials_json" not in content
    assert "GCP_SA_KEY" not in content
    assert "id-token: write" in content


def test_dev_backfill_workflow_writes_dev_env_and_runs_pipeline() -> None:
    content = DEV_BACKFILL_YML.read_text(encoding="utf-8")
    assert "DATABASE_URL_DEV" in content
    assert "APP_ENV=dev" in content
    assert "seed_tickers.py" in content
    assert "backfill_sma.py" in content
    assert "GCP_INSTANCE_NAME" not in content
    assert "secrets.DATABASE_URL }}" not in content


def test_dev_backfill_workflow_deletes_vm_on_failure() -> None:
    content = DEV_BACKFILL_YML.read_text(encoding="utf-8")
    assert "if: always()" in content
    assert "delete-vm:" in content
    assert "verify_dev_backfill.py" in content
