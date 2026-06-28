"""CI checks for GitHub Actions workflows (RFC-007, RFC-009, RFC-011)."""

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
TEST_YML = WORKFLOWS / "test.yml"
DEPLOY_YML = WORKFLOWS / "deploy.yml"
DEV_BACKFILL_YML = WORKFLOWS / "dev-backfill.yml"
WIF_AUTH_ACTION = "google-github-actions/auth@v2"


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def test_all_gcp_workflows_use_workload_identity_federation() -> None:
    """RFC-009: GCP workflows authenticate via WIF — never JSON keys."""
    for path in _workflow_files():
        content = path.read_text(encoding="utf-8")
        if WIF_AUTH_ACTION not in content:
            continue
        assert "workload_identity_provider:" in content, path.name
        assert "GCP_WORKLOAD_IDENTITY_PROVIDER" in content, path.name
        assert "GCP_DEPLOY_SERVICE_ACCOUNT" in content, path.name
        assert "credentials_json" not in content, path.name
        assert "GCP_SA_KEY" not in content, path.name


def test_gcp_workflows_request_oidc_token() -> None:
    """RFC-009: WIF requires id-token: write at workflow level."""
    for path in (DEPLOY_YML, DEV_BACKFILL_YML):
        content = path.read_text(encoding="utf-8")
        assert "id-token: write" in content, path.name


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
    assert WIF_AUTH_ACTION in content
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
    assert "DATABASE_URL=" in content


def test_deploy_workflow_copies_code_from_runner() -> None:
    """Code is shipped from the runner checkout, not pulled on the VM."""
    content = DEPLOY_YML.read_text(encoding="utf-8")
    assert "fansboda-finance.tgz" in content
    assert "tar czf" in content
    assert "gcloud compute scp" in content
    assert "git pull" not in content
    assert "pipenv install --deploy" in content


def test_dev_backfill_workflow_runs_on_dev_push_only() -> None:
    content = DEV_BACKFILL_YML.read_text(encoding="utf-8")
    assert "branches: [dev]" in content
    assert "environment: DEV" in content
    assert "branches: [main]" not in content


def test_dev_backfill_workflow_creates_ephemeral_vm() -> None:
    content = DEV_BACKFILL_YML.read_text(encoding="utf-8")
    assert "data-fetcher-dev" in content
    assert "gcloud compute instances create" in content
    assert "gcloud compute instances delete" in content


def test_dev_backfill_workflow_uses_workload_identity_federation() -> None:
    content = DEV_BACKFILL_YML.read_text(encoding="utf-8")
    assert WIF_AUTH_ACTION in content
    assert "workload_identity_provider:" in content
    assert "GCP_WORKLOAD_IDENTITY_PROVIDER" in content
    assert "GCP_DEPLOY_SERVICE_ACCOUNT" in content
    assert "credentials_json" not in content
    assert "GCP_SA_KEY" not in content
    assert "id-token: write" in content


def test_dev_backfill_workflow_uses_iap_tunnel_for_ssh_and_scp() -> None:
    """RFC-009: dev backfill SSH/SCP must use IAP, not public IP."""
    content = DEV_BACKFILL_YML.read_text(encoding="utf-8")
    remote_commands = content.count("gcloud compute ssh") + content.count(
        "gcloud compute scp"
    )
    assert remote_commands == content.count("--tunnel-through-iap")
    assert remote_commands >= 5


def test_dev_backfill_workflow_deploys_from_runner_checkout() -> None:
    """Code is copied from the CI checkout to the VM — no clone/pull on the VM."""
    content = DEV_BACKFILL_YML.read_text(encoding="utf-8")
    assert "fansboda-finance.tgz" in content
    assert "tar czf" in content
    assert "git pull" not in content
    assert "git fetch" not in content
    assert "repo-url=" not in content
    assert "pipenv install --deploy" in content


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
