# RFC-009: Security & Deploy Authentication

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-007 |
| **PRD** | §7, §8 |
| **Feature** | [Security](../FEATURES.md#security) |

## Summary

No credentials in repo. Production secrets in GitHub. Deploy authenticates via GitHub OIDC JWT + Workload Identity Federation — no long-lived service account JSON keys. Production and dev-backfill SSH/SCP use IAP tunneling.

## Requirements

- `.env` git-ignored; never commit secrets
- `DATABASE_URL` in GitHub secrets → written to VM on deploy
- Deploy SA: OIDC JWT via WIF only — **no `GCP_SA_KEY`**
- Deploy SSH/SCP via `--tunnel-through-iap` (no public IP assumption)
- VM: attached service account via metadata server (no key on disk)
- Cron runs as `fansboda`, not root
- Parameterized SQL in `db/` modules; no SQL in job scripts
- Country-set tables only (`us_*` / `swe_*` / `uk_*`) — no legacy single-set SQL in live paths

## Implementation

### Controls

| Control | Status |
|---------|--------|
| `.env` in `.gitignore` | Done |
| `DATABASE_URL` as GitHub secret | Done |
| Deploy via WIF in `deploy.yml` | Done |
| Dev backfill via WIF in `dev-backfill.yml` | Done |
| No `GCP_SA_KEY` / `credentials_json` in workflows | Done |
| IAP tunnel on all production + dev-backfill SSH/SCP | Done |
| `.env` written with `fansboda:fansboda` mode `600` | Done |
| SQL in `db/` (`country`, `tickers`, `metrics`, `market`, `retention`, `truncate`) | Done |
| Job scripts SQL-free (`fetch_sma`, `seed_tickers`, `backfill_*`, `refresh_tickers`) | Done |
| VM attached SA (external GCP setup) | Documented |
| Cron user `fansboda` | Done (RFC-008) |

### One-time GCP setup (outside repo)

1. Create Workload Identity Pool + GitHub OIDC provider  
   Issuer: `https://token.actions.githubusercontent.com`
2. Create deploy service account (no JSON key)
3. Grant IAM roles:

| Role | Purpose |
|------|---------|
| `roles/compute.instanceAdmin.v1` | SSH/SCP metadata |
| `roles/iam.serviceAccountUser` | On VM's attached SA |
| `roles/compute.osLogin` | OS Login (`osAdminLogin` if sudo needed) |
| `roles/iap.tunnelResourceAccessor` | **Required** for production deploy and dev backfill (`--tunnel-through-iap`) |

4. Bind WIF pool to deploy SA (`roles/iam.workloadIdentityUser`), restricted to this repo; bind `main`/`PROD` for prod deploy and `dev`/`DEV` for dev backfill (RFC-011)

### `deploy.yml` auth

```yaml
permissions:
  contents: read
  id-token: write

- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
    service_account: ${{ secrets.GCP_DEPLOY_SERVICE_ACCOUNT }}
```

Remote steps use `gcloud compute ssh` / `scp` with `--tunnel-through-iap`.

### GitHub secrets

| Secret | Required |
|--------|----------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Yes |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Yes |
| `DATABASE_URL` | Yes (prod env; written to VM `.env`) |
| `GCP_SA_KEY` | **Remove** — deprecated |

### `.env` on VM

```
DATABASE_URL=postgresql://...
APP_ENV=dev
```

Written by deploy with `set +x` (avoid log leakage), then `install -o fansboda -g fansboda -m 600`.

**Temporary:** `APP_ENV=dev` while validating the VM. Cut over to `APP_ENV=production` when ready (RFC-006 / RFC-007).

### Tests

| File | Validates |
|------|-----------|
| `tests/test_workflows.py` | WIF, OIDC `id-token`, no JSON key, IAP on SSH/SCP |
| `tests/test_sql_security.py` | No SQL in job scripts; live `db/` paths use `us_*`/`swe_*`/`uk_*` only; `.gitignore` secrets; deploy `set +x` + `.env` mode 600 |
| `tests/test_verify_dev_backfill.py` | Verify SQL queries country-set tables (incl. `uk_*`) |
| `tests/test_truncate_dev_tables.py` | Truncate targets `us_*`/`swe_*`/`uk_*` only |

## Acceptance criteria

- [x] No secrets committed to repo
- [x] Production `DATABASE_URL` via GitHub secret
- [x] Deploy uses WIF/OIDC JWT (no JSON key)
- [x] Deploy and dev-backfill SSH/SCP use `--tunnel-through-iap`
- [ ] `GCP_SA_KEY` secret removed from GitHub (manual — after first successful WIF deploy)
- [x] Cron user is `fansboda`
- [x] SQL centralized in `db/` with parameterized queries only
- [x] Job scripts contain no SQL strings
- [x] Live DB paths target country-set tables (`us_*` / `swe_*` / `uk_*`)

## Open questions

- Is OS Login enabled on the VM? Determines `compute.osLogin` vs metadata SSH keys.
