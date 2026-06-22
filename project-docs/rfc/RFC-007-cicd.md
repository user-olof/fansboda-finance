# RFC-007: CI/CD

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-003 (tests) |
| **PRD** | §8 |
| **Feature** | [CI/CD](../FEATURES.md#cicd) |

## Summary

GitHub Actions: run `pytest` on push/PR to `main`; deploy to Production VM on push to `main`. Branch protection requires tests to pass.

## Requirements

- **Test workflow:** `pytest` on push/PR to `main`
- **Deploy workflow:** pull repo on VM, `pipenv install --deploy`, write `.env`
- Deploy uses GitHub `production` environment
- No credentials in repo
- Deploy auth via WIF (RFC-009) — no `GCP_SA_KEY`

## Implementation

### Workflows

| Workflow | File | Trigger | Action |
|----------|------|---------|--------|
| Test | `.github/workflows/test.yml` | Push / PR to `main` | Python 3.11, `pipenv install --dev`, `pytest` |
| Deploy | `.github/workflows/deploy.yml` | Push to `main` | WIF auth, SSH, `git pull`, deps, write `.env` |

### Deploy steps

1. Authenticate via WIF (`google-github-actions/auth@v2`)
2. `gcloud compute ssh` — `git pull origin main`, `pipenv install --deploy` as `fansboda`
3. Write `.env` with `DATABASE_URL` and `APP_ENV=production` via `gcloud compute scp`
4. `chown fansboda:fansboda`, `chmod 600` on `.env`

### GitHub secrets

| Secret | Purpose |
|--------|---------|
| `GCP_PROJECT_ID` | GCP project |
| `GCP_ZONE` | VM zone |
| `GCP_INSTANCE_NAME` | VM name |
| `DATABASE_URL` | Neon connection string |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider resource name |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Deploy SA email |

### Branch protection

Run once after Test workflow has completed at least once:

```bash
./scripts/configure-branch-protection.sh
```

Override check context if needed:

```bash
CHECK_CONTEXT="Test / test" ./scripts/configure-branch-protection.sh
```

### Tests

| File | Validates |
|------|-----------|
| `tests/test_workflows.py` | Workflow triggers, WIF, no JSON key, `APP_ENV=production` |
| `tests/test_*.py` | Full suite run in CI |

## Acceptance criteria

- [x] `pytest` runs on push/PR to `main`
- [x] Deploy runs on push to `main`
- [x] Deploy writes `.env` with `fansboda:fansboda` ownership, mode 600
- [x] Deploy uses OIDC/WIF (RFC-009)
- [x] Deploy writes `APP_ENV=production` (RFC-006)
- [x] Branch protection script provided (`scripts/configure-branch-protection.sh`)
- [x] Workflow structure validated in `tests/test_workflows.py`

## Open questions

- Branch protection is a one-time GitHub admin action — not enforced by repo code.
- Dev backfill CI on push to `dev` is specified in [RFC-011](./RFC-011-dev-backfill-ci.md) (PRD §8.1).
