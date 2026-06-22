# RFC-008: Production Operations

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-003, RFC-006, RFC-007, RFC-009 |
| **PRD** | §4, §8.2, §10 |
| **Feature** | [Infrastructure & operations](../FEATURES.md#infrastructure--operations) |

## Summary

A **single** GCP `e2-micro` Always-Free VM runs the weekly pipeline via cron as user `fansboda`. Application code lives at `/opt/fansboda-finance`; Neon Postgres holds `tickers` and `metrics`. First-time VM setup is handled by `scripts/bootstrap-vm.sh`; ongoing code and `.env` updates come from the production deploy workflow (RFC-007, RFC-009).

PRD §8.1 (ephemeral dev VM on push to `dev`) is **out of scope** for this RFC — see [RFC-011](./RFC-011-dev-backfill-ci.md).

## Architecture (PRD §4)

```
+-------------------+   cron Thu @ 11:00 UTC   +---------------------+
|  GCP e2-micro VM  |  ─────────────────────▶  |  fetch_sma.py       |
|  (Debian 12)      |                            |  (weekly job)       |
+-------------------+                                 +----------+----------+
                                                                 │
                          yfinance batch download                │ insert
                                                                 ▼
                                              +----------------------------------+
                                              |  Neon Postgres (prod)            |
                                              |   - tickers  (watchlist)         |
                                              |   - metrics  (SMA history)       |
                                              +----------------------------------+
```

- **Cost target:** one 24/7 `e2-micro` within GCP Always Free + Neon free tier (PRD §1, §7).
- **Outbound only:** yfinance and Neon via `DATABASE_URL`; the VM's attached service account needs no GCP API roles for the weekly job.

## Requirements

### Production VM

| Requirement | Value |
|-------------|-------|
| Machine type | `e2-micro` (Always Free, US region) |
| OS | Debian 12 |
| Timezone | UTC |
| App path | `/opt/fansboda-finance` |
| Cron user | `fansboda` (not `root`) |
| Cron schedule | **Thursdays 11:00 UTC** (`0 11 * * 4`) |
| Log file | `/var/log/fansboda-finance/fetch_sma.log` |
| `.env` | Owned by `fansboda`, mode `600`; readable after every deploy |

### Ownership (PRD §10)

User `fansboda` owns `/opt/fansboda-finance`, the Pipenv venv, `.env`, and the job log. After deploy, the workflow must `chown` `.env` back to `fansboda` (RFC-007).

### Deploy integration (PRD §8.2)

Production deploy is **not** part of this RFC's implementation, but operations depend on it:

- Push to `main` → `.github/workflows/deploy.yml` SSHs to the Production VM, `git pull`, `pipenv install --deploy`, writes `.env` via `gcloud compute scp`.
- Auth: GitHub OIDC JWT + WIF — no `GCP_SA_KEY` (RFC-009).
- `.env` contents: `DATABASE_URL`, `APP_ENV=production` (RFC-006).

### First-time setup (PRD §10)

1. Neon: run `schema.sql`; verify with `scripts/verify_schema.sql`.
2. Existing databases: apply relevant `migrate_*.sql` ([MIGRATIONS.md](../MIGRATIONS.md)).
3. GCP: attach instance service account (no JSON key on disk) existing VM.
4. VM: `sudo bash scripts/bootstrap-vm.sh`.
5. GitHub: secrets + WIF + `production` environment (RFC-009).
6. Push to `main` — deploy writes `.env`.
7. Seed: `pipenv run python seed_tickers.py`.
8. Optional history: `migrate_metrics_history.sql` in Neon, then `pipenv run python backfill_sma.py` once (manual, not cron).
9. Branch protection: `./scripts/configure-branch-protection.sh` (RFC-007).

## Implementation

### Files

| Component | File |
|-----------|------|
| VM bootstrap | `scripts/bootstrap-vm.sh` |
| Schema verification | `scripts/verify_schema.sql` |
| Deploy (pull, deps, `.env`) | `.github/workflows/deploy.yml` (RFC-007) |
| Cron / bootstrap tests | `tests/test_bootstrap_vm.py` |

### `scripts/bootstrap-vm.sh`

Run once as root/sudo on a fresh Debian/Ubuntu instance:

1. Install `git`, `python3`, `pipenv`
2. Create system user `fansboda` if missing (`/opt/fansboda-finance` home)
3. Clone repo to `/opt/fansboda-finance` (override `REPO_URL` if needed)
4. `PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy` as `fansboda`
5. Set timezone UTC (`timedatectl`)
6. Create `/var/log/fansboda-finance/` and `fetch_sma.log` with `fansboda` ownership
7. Install Thursday cron for `fansboda` (replaces any prior `fetch_sma.py` line)

Bootstrap does **not** write `.env` — that comes from the deploy workflow or manual setup.

### Cron entry

PRD §10 documents the minimal cron line:

```
0 11 * * 4 cd /opt/fansboda-finance && pipenv run python fetch_sma.py >> /var/log/fansboda-finance/fetch_sma.log 2>&1
```

Bootstrap installs an **enhanced** line so `get_config()` receives production settings (RFC-006):

```
0 11 * * 4 cd /opt/fansboda-finance && set -a && [ -f .env ] && . ./.env && set +a && PIPENV_VENV_IN_PROJECT=1 pipenv run python fetch_sma.py >> /var/log/fansboda-finance/fetch_sma.log 2>&1
```

| Enhancement | Why |
|-------------|-----|
| `set -a` / `. ./.env` | Loads `DATABASE_URL` and `APP_ENV=production` |
| `[ -f .env ]` | Cron does not fail before first deploy |
| `PIPENV_VENV_IN_PROJECT=1` | Uses project-local `.venv` |

### VM attached service account

Separate from the **deploy** service account (RFC-009). The instance SA is the runtime identity via the metadata server. No GCP roles required for `fetch_sma.py` — outbound HTTPS to yfinance and Neon only.

### Operational runbook

| Task | Command |
|------|---------|
| Check last cron run | `tail -100 /var/log/fansboda-finance/fetch_sma.log` |
| Manual weekly run | `sudo -u fansboda bash -c 'cd /opt/fansboda-finance && set -a && . ./.env && set +a && PIPENV_VENV_IN_PROJECT=1 pipenv run python fetch_sma.py'` |
| Verify data | `SELECT * FROM metrics ORDER BY trading_date DESC, ticker LIMIT 10;` |
| Check retention span | `SELECT MIN(trading_date), MAX(trading_date), COUNT(*) FROM metrics;` |

### First-time setup checklist

```
[ ] Neon prod: schema.sql (+ migrate_*.sql if upgrading)
[ ] Neon: scripts/verify_schema.sql
[ ] GCP: one e2-micro in Always Free US region; attach instance SA
[ ] VM: sudo bash scripts/bootstrap-vm.sh
[ ] GitHub: secrets + WIF + production environment (RFC-009)
[ ] Push to main: deploy writes .env (RFC-007)
[ ] Seed: pipenv run python seed_tickers.py
[ ] Optional: migrate_metrics_history.sql + backfill_sma.py (one-off)
[ ] GitHub: ./scripts/configure-branch-protection.sh
[ ] Verify: SELECT * FROM metrics ORDER BY trading_date DESC LIMIT 10;
```

## Acceptance criteria

- [x] Bootstrap script installs deps and creates `fansboda` user
- [x] Bootstrap sets timezone UTC and log directory ownership
- [x] Bootstrap cron uses Thursday schedule (`0 11 * * 4`)
- [x] Bootstrap cron sources `.env` and sets `PIPENV_VENV_IN_PROJECT=1`
- [x] Log path documented and created by bootstrap
- [x] First-time and runbook steps documented
- [x] Tests in `tests/test_bootstrap_vm.py`
- [x] Single production VM model documented (PRD §1 cost target)

## Related RFCs

| RFC | Relationship |
|-----|--------------|
| RFC-006 | Cron loads `APP_ENV=production` and config tunables from `.env` |
| RFC-007 | Deploy workflow updates code and `.env` on the Production VM |
| RFC-009 | WIF deploy auth; `.env` ownership after deploy |

## Open questions

- **Log rotation** for `/var/log/fansboda-finance/` — not in PRD; defer.
- **§8.1 dev pipeline** — covered by [RFC-011](./RFC-011-dev-backfill-ci.md).
