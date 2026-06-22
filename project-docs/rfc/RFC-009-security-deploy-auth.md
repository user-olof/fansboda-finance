# RFC-009: Security & Deploy Authentication

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-007 |
| **PRD** | §7, §8 |
| **Feature** | [Security](../FEATURES.md#security) |

## Summary

No credentials in repo. Production secrets in GitHub. Deploy authenticates via GitHub OIDC JWT + Workload Identity Federation — no long-lived service account JSON keys.

## Requirements

- `.env` git-ignored; never commit secrets
- `DATABASE_URL` in GitHub secrets → written to VM on deploy
- Deploy SA: OIDC JWT via WIF only — **no `GCP_SA_KEY`**
- VM: attached service account via metadata server (no key on disk)
- Cron runs as `fansboda`, not root
- Parameterized SQL in `db/` modules; no SQL in job scripts

## Implementation

### Controls

| Control | Status |
|---------|--------|
| `.env` in `.gitignore` | Done |
| `DATABASE_URL` as GitHub secret | Done |
| Deploy via WIF in `deploy.yml` | Done |
| No `GCP_SA_KEY` in workflow | Done |
| SQL in `db/tickers.py`, `db/metrics.py` | Done |
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
| `roles/iap.tunnelResourceAccessor` | Only if using IAP tunnel |

4. Bind WIF pool to deploy SA (`roles/iam.workloadIdentityUser`), restricted to this repo / `main` / `production` environment

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

### GitHub secrets

| Secret | Required |
|--------|----------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Yes |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Yes |
| `GCP_SA_KEY` | **Remove** — deprecated |

### `.env` on VM

```
DATABASE_URL=postgresql://...
APP_ENV=production
```

Written by deploy; `chown fansboda:fansboda`; `chmod 600`.

### Tests

`tests/test_workflows.py` — asserts WIF config present, no JSON key auth, OIDC token permission.

## Acceptance criteria

- [x] No secrets committed to repo
- [x] Production `DATABASE_URL` via GitHub secret
- [x] Deploy uses WIF/OIDC JWT (no JSON key)
- [ ] `GCP_SA_KEY` secret removed from GitHub (manual — after first successful WIF deploy)
- [x] Cron user is `fansboda`
- [x] SQL centralized in `db/` with parameterized queries only

## Open questions

- Is OS Login enabled on the VM? Determines `compute.osLogin` vs metadata SSH keys.
