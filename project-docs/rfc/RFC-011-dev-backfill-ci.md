# RFC-011: Dev Backfill CI

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-002, RFC-005, RFC-006, RFC-007, RFC-009 |
| **PRD** | §8.1 |
| **Feature** | [CI/CD — dev backfill](../FEATURES.md#cicd--dev-backfill-prd-81) |

## Summary

On push to **`dev`**, GitHub Actions spins up an ephemeral GCP VM (`data-fetcher-dev`), deploys the repo, runs watchlist seeding and historical backfill against a **Neon dev branch**, verifies the run, and **always** deletes the VM. This validates the full data pipeline without keeping a second 24/7 `e2-micro` (PRD §1 cost target).

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
| `dev-backfill.yml` | Push to `dev` | Ephemeral `data-fetcher-dev` VM |

### Target design

#### Workflow chain

Use a single workflow with dependent jobs (or reusable workflows) so each step gates the next:

| Job | Runs when | Action |
|-----|-----------|--------|
| `spin-up-vm` | Push to `dev` | `gcloud compute instances create data-fetcher-dev` — Debian 12, `e2-micro`, tag `dev-backfill`; wait until `gcloud compute ssh --tunnel-through-iap --quiet` succeeds |
| `deploy` | Spin-up succeeds | Clone/pull repo at `/opt/fansboda-finance`, `pipenv install --deploy`, SCP `.env` with dev `DATABASE_URL` and `APP_ENV=dev` (all SSH/SCP via `--tunnel-through-iap`) |
| `collect-data` | Deploy succeeds | SSH: `seed_tickers.py`, then `backfill_sma.py` (RFC-002, RFC-005) |
| `verify` | Data collection succeeds | Parse job logs; SQL checks against dev DB (`scripts/verify_dev_backfill.py`); print summary |
| `delete-vm` | Always after pipeline jobs | `gcloud compute instances delete data-fetcher-dev --quiet` in an `if: always()` job |

Reuse patterns from RFC-007 (WIF auth, SCP `.env`, `chown fansboda:fansboda`) and RFC-008 (`scripts/bootstrap-vm.sh` steps or a slim `scripts/bootstrap-dev-vm.sh` invoked on first boot).

#### Data collection order

On a fresh Neon dev branch:

1. Apply `schema.sql` (one-time Neon setup outside workflow, or a workflow pre-step).
2. `pipenv run python seed_tickers.py` — populate `tickers` (RFC-002).
3. `pipenv run python backfill_sma.py` — bootstrap `metrics` history (RFC-005).

`fetch_sma.py` is optional in this pipeline; backfill already produces historical snapshots. Include it only if verifying the weekly job path on dev is required.

#### Configuration (RFC-006)

| Setting | Dev pipeline value |
|---------|-------------------|
| `APP_ENV` | `dev` → `DevConfig` |
| `database_url` | Neon **dev branch** connection string (GitHub secret) |
| Backfill tunables | Same defaults as `DevConfig` unless overridden |

#### GitHub secrets / environment

| Secret | Purpose |
|--------|---------|
| `DATABASE_URL_DEV` | Neon dev branch connection string (**separate from prod**) |
| `GCP_PROJECT_ID` | Shared with production deploy |
| `GCP_ZONE` | Zone for ephemeral VM |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider (RFC-009) |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Deploy SA — may need **additional** IAM for instance create/delete |

Use a GitHub **`DEV`** environment (distinct from `production`) with secrets scoped to `dev` branch pushes.

#### Deploy authentication (RFC-009)

Same WIF/OIDC path as `deploy.yml` — no `GCP_SA_KEY`. Extend WIF binding to allow the `dev` branch (or `DEV` environment) in addition to `main` / `production`.

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
- Optionally connect to Neon dev branch and run sanity queries, e.g.:
  - `SELECT COUNT(DISTINCT ticker) FROM metrics;`
  - Compare against `SELECT COUNT(*) FROM tickers;`
- Print a human-readable summary in the Actions log (pass / warn / fail).

Fatal script errors fail the workflow before verification; verification catches partial data quality issues.

#### Files to create / modify

| File | Action |
|------|--------|
| `.github/workflows/dev-backfill.yml` | **Done** — ephemeral VM pipeline on push to `dev` |
| `scripts/bootstrap-dev-vm.sh` | **Done** — GCE startup bootstrap (no cron) |
| `scripts/verify_dev_backfill.py` | **Done** — log + DB verification for CI |
| `tests/test_workflows.py` | **Done** — dev workflow assertions |
| `project-docs/rfc/README.md` | Update status when implemented |

### Reuse

| RFC | Reuse |
|-----|-------|
| RFC-002 | `seed_tickers.py` |
| RFC-005 | `backfill_sma.py` |
| RFC-006 | `DevConfig`, `get_config()` |
| RFC-007 | Workflow structure, `.env` SCP pattern, `pipenv install --deploy` |
| RFC-009 | WIF auth block; extend branch/environment binding |
| RFC-008 | VM paths (`/opt/fansboda-finance`), `fansboda` user, log layout (if bootstrap reused) |

## Acceptance criteria

- [x] Workflow triggers on push to `dev` only
- [x] Creates ephemeral VM named `data-fetcher-dev`
- [x] Deploys code and writes `.env` with `DATABASE_URL_DEV` and `APP_ENV=dev`
- [x] Runs `seed_tickers.py` and `backfill_sma.py` on the dev VM
- [x] Verification job reports data quality summary in Actions log
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

## Open questions

- **Neon dev branch schema:** apply `schema.sql` manually once, or add a workflow step / migration job?
- **Verification thresholds:** what counts as failure — any failed batch, or &lt; N tickers with metrics?
- **Separate deploy SA for dev** vs. extend production deploy SA IAM?
- **Push to `dev` vs. PR to `dev`:** PRD says push; should PRs run a dry-run without VM create?
