# RFC-011: Dev Backfill CI

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-002, RFC-005, RFC-006, RFC-007, RFC-009 |
| **PRD** | §8.1 |
| **Feature** | [CI/CD — dev backfill](../FEATURES.md#cicd--dev-backfill-prd-81) |

## Summary

On push to **`dev`**, GitHub Actions spins up an ephemeral GCP VM (`data-fetcher-dev`), deploys the repo via tarball, runs watchlist seeding and historical backfill against a **Neon dev branch** (`us_*` / `swe_*` tables), verifies the run, and **always** deletes the VM. This validates the full data pipeline without keeping a second 24/7 `e2-micro` (PRD §1 cost target).

Production CI/CD (RFC-007) and production VM ops (RFC-008) are unchanged.

## Requirements (PRD §8.1)

| Step | Requirement |
|------|-------------|
| Spin up VM | On push to `dev`, create `data-fetcher-dev` in GCP (tag `dev-backfill`). Firewall must allow GitHub Actions SSH via IAP (`tcp:22` from `35.235.240.0/20`, scoped to that tag). Wait until `gcloud compute ssh --tunnel-through-iap` succeeds. |
| Deploy | After spin-up succeeds, install deps and write `.env` on the dev VM |
| Data collection | After deploy succeeds, run pipeline scripts; store results in Neon **dev branch** |
| Verification | After data collection completes without interrupting error, analyze missing data, failed downloads, etc.; print results |
| Delete VM | Tear down `data-fetcher-dev` — **always**, including on failure |

### Non-goals

- No cron on the dev VM (RFC-008 production schedule only).
- No deploy to the long-lived Production VM (RFC-007).
- Not a replacement for local development or manual `backfill_sma.py` runs.

## Architecture

```
push to dev
    │
    ▼
┌─────────────────┐  WIF + IAP (RFC-009)  ┌──────────────────────┐
│ GitHub Actions  │ ────────────────────▶ │ data-fetcher-dev     │
│ workflow chain  │ gcloud create/ssh/iap │ (ephemeral e2-micro) │
└────────┬────────┘                       └──────────┬───────────┘
         │                                           │
         │                              seed_tickers.py
         │                              backfill_sma.py
         │                                           │
         │                                           ▼
         │                              ┌──────────────────────┐
         │                              │ Neon Postgres        │
         │                              │ (dev branch)         │
         │                              │ us_* / swe_* tables  │
         │                              └──────────────────────┘
         ▼
   verify logs / DB checks
         │
         ▼
   delete VM (finally)
```

**Cost rationale:** one production VM runs 24/7; dev VM exists only for the workflow duration (FEATURES.md).

## Implementation

### Current state

| Workflow | Trigger | Scope |
|----------|---------|-------|
| `test.yml` | Push / PR to `main` | `pytest` |
| `deploy.yml` | Push to `main` | Production VM |
| `dev-backfill.yml` | Push to `dev` (+ `workflow_dispatch`) | Ephemeral `data-fetcher-dev` VM |

### Target design

#### Workflow chain

Use a single workflow with dependent jobs so each step gates the next:

| Job | Runs when | Action |
|-----|-----------|--------|
| `spin-up-vm` | Push to `dev` | `gcloud compute instances create data-fetcher-dev` — Debian 12, `e2-micro`, tag `dev-backfill`; wait until bootstrap marker via `gcloud compute ssh --tunnel-through-iap` |
| `deploy` | Spin-up succeeds | SCP tarball to `/opt/fansboda-finance`, ensure `pipenv`, `pipenv install --deploy`, SCP `.env` with `DATABASE_URL` + `APP_ENV=dev`; apply schema via `scripts/apply_migrations.sh` (all SSH/SCP via `--tunnel-through-iap`) |
| `collect-data` | Deploy succeeds | SSH: `seed_tickers.py`, then `backfill_sma.py` (RFC-002, RFC-005) |
| `verify` | Data collection succeeds | Parse job logs; SQL checks against country tables (`scripts/verify_dev_backfill.py`); print summary |
| `delete-vm` | Always after pipeline jobs | `gcloud compute instances delete data-fetcher-dev --quiet` in an `if: always()` job |

Reuse patterns from RFC-007 (WIF auth, tarball + SCP `.env`, `chown fansboda:fansboda`) and RFC-008 (`scripts/bootstrap-dev-vm.sh` on first boot — no cron).

#### Data collection order

On the Neon dev branch:

1. `scripts/apply_migrations.sh` — `schema.sql` + conditional legacy upgrades + step 11 country split.
2. `pipenv run python seed_tickers.py` — populate `us_tickers` / `swe_tickers` (RFC-002).
3. `pipenv run python backfill_sma.py` — bootstrap `us_metrics` / `swe_metrics` history (RFC-005).

`fetch_sma.py` is optional in this pipeline; backfill already produces historical snapshots.

#### Configuration (RFC-006)

| Setting | Dev pipeline value |
|---------|--------------------|
| `APP_ENV` | `dev` → `DevConfig` |
| `database_url` | Neon **dev branch** connection string (GitHub `DEV` environment secret) |
| Backfill tunables | Same defaults as `DevConfig` unless overridden |

#### GitHub secrets / environment

| Secret | Purpose |
|--------|---------|
| `DATABASE_URL` | Neon **dev branch** URL in the `DEV` environment (written as `DATABASE_URL` in VM `.env`) |
| `GCP_PROJECT_ID` | Shared with production deploy |
| `GCP_ZONE` | Zone for ephemeral VM |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider (RFC-009) |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Deploy SA — needs IAM for instance create/delete + IAP |

Use a GitHub **`DEV`** environment (distinct from `PROD`) with secrets scoped to `dev` branch pushes.

#### Deploy authentication (RFC-009)

Same WIF/OIDC path as `deploy.yml` — no `GCP_SA_KEY`. Extend WIF binding to allow the `dev` branch / `DEV` environment in addition to `main` / `PROD`.

#### Firewall (one-time GCP setup)

Dev backfill SSH uses IAP, not a public-IP SSH rule. Create (or verify) an ingress firewall rule on the VM network:

| Setting | Value |
|---------|-------|
| Direction | INGRESS |
| Source | `35.235.240.0/20` (Google IAP TCP forwarding range) |
| Allow | `tcp:22` |
| Target tags | `dev-backfill` |

The workflow creates the VM with `--tags=dev-backfill`. See [Google IAP firewall docs](https://cloud.google.com/iap/docs/using-tcp-forwarding#create-firewall-rule).

#### Additional IAM (deploy service account)

RFC-009 roles cover SSH to an **existing** instance. RFC-011 additionally requires:

| Role | Purpose |
|------|---------|
| `roles/compute.instanceAdmin.v1` | Create and delete `data-fetcher-dev`; SSH/SCP metadata |
| `roles/iap.tunnelResourceAccessor` | IAP SSH (`--tunnel-through-iap`) from GitHub Actions |
| `roles/compute.osLogin` (or `osAdminLogin`) | SSH login when OS Login is enabled |

Confirm least-privilege: create/delete only in the target zone, or use a dedicated dev deploy SA.

#### Verification job

After `collect-data` succeeds (exit 0):

- Scan stdout/stderr for failed batches, non-zero exit markers, and RFC-005 summary lines (generated / inserted / skipped counts).
- Connect to Neon dev branch and run sanity queries over country sets:
  - `SELECT COUNT(*) FROM us_tickers` / `swe_tickers`
  - `SELECT COUNT(DISTINCT ticker) FROM us_metrics` / `swe_metrics`
- Print a human-readable summary in the Actions log (pass / fail).

Fatal script errors fail the workflow before verification; verification catches partial data quality issues.

#### Files

| File | Action |
|------|--------|
| `.github/workflows/dev-backfill.yml` | Ephemeral VM pipeline on push to `dev` |
| `scripts/bootstrap-dev-vm.sh` | GCE startup bootstrap (no cron) |
| `scripts/apply_migrations.sh` | `schema.sql` + legacy-if-needed + step 11 |
| `scripts/verify_dev_backfill.py` | Log + country-table DB verification |
| `tests/test_workflows.py` | Dev workflow assertions |
| `tests/test_bootstrap_dev_vm.py` | Bootstrap script assertions |
| `tests/test_verify_dev_backfill.py` | Verification script assertions |

### Reuse

| RFC | Reuse |
|-----|-------|
| RFC-002 | `seed_tickers.py` → `us_tickers` / `swe_tickers` |
| RFC-005 | `backfill_sma.py` → `us_metrics` / `swe_metrics` |
| RFC-006 | `DevConfig`, `get_config()` |
| RFC-007 | Workflow structure, tarball + `.env` SCP, `pipenv install --deploy` |
| RFC-009 | WIF auth; IAP SSH/SCP |
| RFC-008 | VM paths (`/opt/fansboda-finance`), `fansboda` user (no prod cron) |

## Acceptance criteria

- [x] Workflow triggers on push to `dev` only (plus manual `workflow_dispatch`)
- [x] Creates ephemeral VM named `data-fetcher-dev`
- [x] Deploys code via tarball and writes `.env` with `APP_ENV=dev`
- [x] Applies country schema via `apply_migrations.sh` (fresh-safe)
- [x] Runs `seed_tickers.py` and `backfill_sma.py` on the dev VM
- [x] Verification job reports data quality summary against `us_*` / `swe_*`
- [x] Deletes VM in a final job even when earlier jobs fail
- [x] Uses WIF/OIDC — no `GCP_SA_KEY` (RFC-009)
- [x] Does not touch Production VM or prod `DATABASE_URL`
- [x] SSH/SCP use `--tunnel-through-iap` (not public IP)
- [x] Firewall allows IAP (`35.235.240.0/20`) to reach tagged dev VM on port 22
- [x] Workflow structure validated in `tests/test_workflows.py`

## Related RFCs

| RFC | Relationship |
|-----|--------------|
| RFC-007 | Production CI/CD on `main` — separate trigger and target |
| RFC-008 | Long-lived production VM and cron — not used by dev pipeline |
| RFC-009 | Shared deploy auth; IAM may need create/delete scope |
| RFC-005 | Backfill script invoked during data collection |
| RFC-001 | Country table sets verified by `verify_dev_backfill.py` |

## Open questions

- **Verification thresholds:** what counts as failure — any failed batch, or &lt; N tickers with metrics?
- **Separate deploy SA for dev** vs. extend production deploy SA IAM?
- **Push to `dev` vs. PR to `dev`:** PRD says push; should PRs run a dry-run without VM create?
