# RFC-007: CI/CD

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-003 (tests) |
| **PRD** | §8.2 |
| **Feature** | [CI/CD — production](../FEATURES.md#cicd--production-prd-82-implemented) |

## Summary

GitHub Actions: run `pytest` on push/PR to `main`; deploy to Production VM on push to `main`. Branch protection requires tests to pass. Dev backfill (PRD §8.1) is [RFC-011](./RFC-011-dev-backfill-ci.md), not this RFC.

Deploy ships a **tarball** from the runner checkout (not `git pull` on the VM), installs deps with Pipenv, and writes `.env`. SSH/SCP use IAP (RFC-009).

**Temporary (VM validation):** deploy currently writes `APP_ENV=dev` (not production cutover). Switch to `APP_ENV=production` when ready.

## Requirements

- **Test workflow:** `pytest` on push/PR to `main`
- **Deploy workflow:** copy code to VM, ensure `pipenv`, `pipenv install --deploy`, write `.env`
- Deploy uses GitHub `PROD` environment
- No credentials in repo
- Deploy auth via WIF (RFC-009) — no `GCP_SA_KEY`
- Deploy SSH/SCP via `--tunnel-through-iap`

## Implementation

### Workflows

| Workflow | File | Trigger | Action |
|----------|------|---------|--------|
| Test | `.github/workflows/test.yml` | Push / PR to `main` | Python 3.11, `pipenv install --dev`, `pytest` |
| Deploy | `.github/workflows/deploy.yml` | Push to `main` | WIF auth, IAP SCP/SSH, tarball unpack, deps, write `.env` |

### Deploy steps

1. Authenticate via WIF (`google-github-actions/auth@v2`)
2. Package repo checkout as `fansboda-finance.tgz` (exclude `.git` / `.venv`)
3. `gcloud compute scp --tunnel-through-iap` tarball to the VM
4. `gcloud compute ssh --tunnel-through-iap` — unpack to `/opt/fansboda-finance`, ensure `fansboda` user + `pipenv`, run `PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy` as `fansboda`
5. Write `.env` with `DATABASE_URL` and `APP_ENV=dev` (temporary VM validation; cut over to `APP_ENV=production` later) via SCP + `install -o fansboda -g fansboda -m 600`

Schema upgrades (including country-table step 11) are applied manually per [MIGRATIONS.md](../MIGRATIONS.md) — not in this workflow.

### GitHub secrets

| Secret | Purpose |
|--------|---------|
| `GCP_PROJECT_ID` | GCP project |
| `GCP_ZONE` | VM zone |
| `GCP_INSTANCE_NAME` | VM name |
| `DATABASE_URL` | Neon production connection string |
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
| `tests/test_workflows.py` | Triggers, WIF, IAP, tarball deploy, temporary `APP_ENV=dev`, no JSON key |
| `tests/test_*.py` | Full suite run in CI |

## Acceptance criteria

- [x] `pytest` runs on push/PR to `main`
- [x] Deploy runs on push to `main`
- [x] Deploy copies code via tarball (no `git pull` on VM)
- [x] Deploy ensures `pipenv` when missing, then `pipenv install --deploy`
- [x] Deploy writes `.env` with `fansboda:fansboda` ownership, mode 600
- [ ] Deploy writes `APP_ENV=production` (RFC-006) — still temporary `APP_ENV=dev` during VM validation
- [x] Deploy uses OIDC/WIF and IAP SSH/SCP (RFC-009)
- [x] Branch protection script provided (`scripts/configure-branch-protection.sh`)
- [x] Workflow structure validated in `tests/test_workflows.py`

## Open questions

- Branch protection is a one-time GitHub admin action — not enforced by repo code.
- Dev backfill CI on push to `dev` is specified in [RFC-011](./RFC-011-dev-backfill-ci.md) (PRD §8.1).
