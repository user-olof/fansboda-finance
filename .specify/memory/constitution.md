<!--
Sync Impact Report
- Version change: (template) → 1.0.0
- Modified principles: none (initial adoption; all placeholders replaced)
- Added principles:
  I. Weekly Batch Only
  II. Near-Zero Cost
  III. Data Pipeline Only — No UI or API
  IV. Parameterized SQL in db/ Only
  V. Keyless Authentication and No Secrets in the Repo
  VI. Schema Changes Through schema.sql and migrate_*.sql
  VII. Pure Logic Separated from I/O, with Unit Tests
- Added sections: Operational Constraints; Development Workflow; Governance
- Removed sections: none
- Templates checked: .specify/templates/plan-template.md, spec-template.md,
  tasks-template.md read the constitution at runtime — no edits required
- Follow-up TODOs: none
-->

# fansboda-finance Constitution

## Core Principles

### I. Weekly Batch Only

The pipeline MUST run as a single unattended weekly job (Saturdays 11:00 UTC via cron
on the production VM). Features MUST NOT add intraday, real-time, streaming, or
event-driven data collection. One-off bootstrap scripts (`backfill_sma.py`,
`backfill_market.py`, `compute_indices.py` rebuilds) MUST stay manual and MUST NOT be
cron-scheduled in production; `backfill_sma.py` MUST run per country set
(`--country us|swe|uk`).

Rationale: the consumers (`fansboda`) work on weekly SMA data; a weekly batch keeps
the system simple, cheap, and within data-provider rate limits.

### II. Near-Zero Cost

Monthly operating cost MUST stay at ~$0 within the GCP Always Free tier (one `e2-micro`
VM) and the Neon free tier. A change that adds paid infrastructure, a second always-on
service, or storage growth beyond the rolling retention window (default 365 days)
MUST be rejected or explicitly approved by the owner with the cost stated in its spec.

Rationale: this is a single-owner hobby pipeline; cost is a hard constraint.

### III. Data Pipeline Only — No UI or API

The repository MUST only produce data in Neon Postgres; consumers read it directly.
It MUST NOT add a user interface, HTTP API, authentication layer, dashboard, or
portfolio / order / transaction tracking. Indicators are limited to SMA-50, SMA-200,
current price, and their derived fields (momentum, z-score, weekly growth, equal-weighted
indices); EMA, RSI, MACD, or other windows MUST NOT be added without an owner request.
Golden / Death Cross signals belong to `fansboda`. The only notification this
repository sends is the data-quality outlier email.

Rationale: keeping the scope narrow keeps the job small, reviewable, and free to run;
presentation and signals live in the consumer repository.

### IV. Parameterized SQL in db/ Only

All SQL MUST live in the `db/` package; job and script entrypoints MUST call `db/`
functions and MUST NOT contain SQL. Runtime values MUST be passed as driver parameters
(`%s`); they MUST NOT be interpolated into SQL strings. Only fixed identifiers from
code (e.g. per-country table names from `CountrySet`) MAY be formatted into SQL, at
module load.

Rationale: one place to review queries, and no SQL injection surface.

### V. Keyless Authentication and No Secrets in the Repo

Credentials MUST NOT be committed; `.env` stays git-ignored. GitHub Actions MUST
authenticate to GCP with a short-lived OIDC JWT through Workload Identity Federation —
no `GCP_SA_KEY` or JSON service-account keys. The VM MUST use its attached service
account via the metadata server. The outlier email MUST use the Gmail API with
domain-wide delegation, signing the JWT through the IAM Credentials API (`signBlob`),
scope `gmail.send` only — no JSON key, OAuth refresh token, or SMTP password.
Production `DATABASE_URL`, `ALERT_EMAIL_FROM`, and `ALERT_EMAIL_TO` live only in the
GitHub `production` environment secrets and the VM `.env`. Cron MUST run as the Linux
user `fansboda`, not root.

Rationale: long-lived keys are the main leak risk for a small unattended system.

### VI. Schema Changes Through schema.sql and migrate_*.sql

Every DDL change MUST be made in `schema.sql` (fresh databases) and an idempotent
`migrate_*.sql` file (existing databases), committed together, with its step and
ordering documented in `project-docs/MIGRATIONS.md` and wired into
`scripts/apply_migrations.sh` and `scripts/verify_schema.sql`. Python code MUST NOT
issue ad-hoc DDL. Destructive steps (dropping tables or columns) MUST be separate
migration steps applied only after every consumer has moved off the old structure,
with a snapshot taken first.

Rationale: production and dev databases must be upgradeable reproducibly and safely.

### VII. Pure Logic Separated from I/O, with Unit Tests

Parsing, SMA math, growth, index chaining, outlier checks, and other computation MUST
live in pure functions separate from database and yfinance I/O. Every change to pure
logic MUST come with unit tests; I/O code MUST be tested with mocked database and
yfinance calls. Tests MUST NOT touch the production or `.env` database or the network.
`pipenv run pytest` MUST pass before merge.

Rationale: the job runs unattended; correctness is proven by fast, offline tests.

## Operational Constraints

- Python 3.11+; dependencies through Pipenv only (`Pipfile` / `Pipfile.lock`, no
  `requirements.txt`); `pipenv install --deploy` on VMs and CI production paths.
- Configuration MUST be centralized in `config.py` (`DevConfig` loads `.env`,
  `ProdConfig` reads environment variables, selected by `APP_ENV`); scripts MUST NOT
  scatter `os.getenv` calls.
- yfinance access MUST batch downloads with `threads=False`, delay between batches, and
  retry 429 / rate-limit / timeout / connection errors with exponential backoff; a
  failed batch is logged and the run continues.
- Jobs MUST be idempotent: re-running the weekly job, backfills, or index rebuilds is
  safe; metric rows upsert per `(ticker, week_start)` and only a newer bar replaces a
  row.
- Weekly growth MUST be computed from a single adjusted download (never a ratio of two
  stored rows except for gap weeks), and outlier stock-weeks MUST be excluded from
  indices.
- Shared logic (`download_batch`, `compute_smas`, `metric_row_from_history`,
  `chunked`) MUST be reused rather than duplicated.

## Development Workflow

- New behavior starts as a Spec Kit feature (`/speckit-specify` → `/speckit-plan` →
  `/speckit-tasks` → `/speckit-implement`) under `specs/`. `project-docs/PRD.md` and
  `project-docs/rfc/` are the frozen baseline describing the system as built through
  RFC-018; they are reference context, not the place for new requirements.
- Plans MUST pass a Constitution Check against Principles I–VII; any deviation MUST be
  justified in the plan's Complexity Tracking table and approved by the owner.
- Diffs MUST stay minimal and match surrounding naming and patterns; no unrelated
  refactors.
- `test.yml` MUST pass on `main` (required check); `deploy.yml` deploys only a commit
  that passed tests on `main`. `dev-backfill.yml` is manual only.
- Test outlier-email delivery only with `scripts/send_test_email.py`, never by running
  `fetch_sma.py`.

## Governance

This constitution supersedes other project practices where they conflict.
`.cursor/rules/RULES.mdc` is the runtime guidance file for agents and MUST stay
consistent with it.

Amendments are made with `/speckit-constitution`, reviewed in a pull request, and MUST
update the Sync Impact Report. Versioning follows semantic versioning: MAJOR for
removing or redefining a principle, MINOR for a new principle or materially expanded
guidance, PATCH for clarifications and wording.

Every spec, plan, and pull request review MUST check compliance with the principles
above; scope extensions (Principle III) require an explicit owner request before work
starts.

**Version**: 1.0.0 | **Ratified**: 2026-10-07 | **Last Amended**: 2026-10-07
