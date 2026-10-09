# RFC Index — fansboda-finance

Request for Comments documents derived from [PRD.md](../PRD.md) and [FEATURES.md](../FEATURES.md). Each RFC describes one feature with priority, status, and implementation detail.

## Priority legend

| Priority | Meaning |
|----------|---------|
| **P0** | Foundation — must exist before anything else runs |
| **P1** | Core product — minimum viable weekly pipeline |
| **P2** | Bootstrap, config, deploy, and production operations |
| **P3** | Planned enhancements — not required for initial production |

## RFC list

| Order | RFC | Feature | Priority | Status |
|------:|-----|---------|----------|--------|
| 1 | [RFC-001](./RFC-001-data-model.md) | Data model (`us_*` / `swe_*` / `uk_*` table sets) | P0 | Implemented |
| 2 | [RFC-002](./RFC-002-watchlist-seeding.md) | Watchlist seeding | P1 | Implemented |
| 3 | [RFC-003](./RFC-003-weekly-sma-fetch.md) | Weekly SMA fetch | P1 | Implemented |
| 4 | [RFC-004](./RFC-004-data-retention.md) | Rolling data retention | P1 | Implemented |
| 5 | [RFC-005](./RFC-005-historical-backfill.md) | Historical backfill | P2 | Implemented |
| 6 | [RFC-006](./RFC-006-configuration.md) | Centralized configuration | P2 | Implemented |
| 7 | [RFC-007](./RFC-007-cicd.md) | CI/CD (test & deploy) | P2 | Implemented |
| 8 | [RFC-008](./RFC-008-production-operations.md) | Production VM & cron | P2 | Implemented |
| 9 | [RFC-009](./RFC-009-security-deploy-auth.md) | Security & deploy authentication | P2 | Implemented |
| 10 | [RFC-010](./RFC-010-metadata-refresh.md) | Ad-hoc metadata refresh | P3 | Implemented |
| 11 | [RFC-011](./RFC-011-dev-backfill-ci.md) | Dev backfill CI (ephemeral VM, IAP SSH) | P2 | Implemented |
| 12 | [RFC-012](./RFC-012-normalized-ratios-market.md) | Momentum, z-score & market aggregates | P1 | Implemented |
| 13 | RFC-013 | Golden Cross & Death Cross detection | — | Moved to `fansboda` repo |
| 14 | [RFC-014](./RFC-014-sector-trends.md) | Sector trend averages (`*_by_sector`) | P3 | Superseded by RFC-018 |
| 15 | [RFC-015](./RFC-015-equity-indices.md) | Equal-weighted equity indices (`indices`) | P3 | Implemented |
| 16 | [RFC-016](./RFC-016-weekly-growth-columns.md) | Weekly growth columns (split-robust index chaining) | P3 | Implemented |
| 17 | [RFC-017](./RFC-017-outlier-guard-email.md) | Outlier guard & data-quality email (Gmail API) | P3 | Implemented |
| 18 | [RFC-018](./RFC-018-sector-indices.md) | Sector indices in `indices` (`pct_uptrend`, `z_score`, `currency`); retire `*_by_sector` | P3 | Implemented |

## Dependency graph

```
RFC-001 (schema: us_* / swe_* / uk_* sets)
    ├── RFC-002 (seed tickers; optional --country)
    │       ├── RFC-003 (weekly fetch)
    │       │       ├── RFC-004 (retention)
    │       │       └── RFC-012 (momentum / z_score + market momentum_mean/std)
    │       │               └── RFC-014 (equal-weighted sector trends → *_by_sector)
    │       │                       └── RFC-015 (equal-weighted country indices → indices)
    │       │                               └── RFC-016 (weekly growth columns → split-robust chaining)
    │       │                                       └── RFC-017 (outlier guard + Gmail data-quality email)
    │       │                                               └── RFC-018 (sector indices in indices; retires *_by_sector)
    │       └── RFC-005 (backfill; required --country)
    │               └── RFC-012 (momentum on backfill; scoped with FR-18)
    ├── RFC-006 (config) ── applies to all scripts
    ├── RFC-007 (CI/CD, main) ── RFC-009 (WIF auth)
    │       └── RFC-011 (dev backfill CI — manual workflow_dispatch + country input)
    └── RFC-008 (prod VM ops)
            └── RFC-010 (metadata refresh)
```

## How to use

1. **PRD** is authoritative for requirements and acceptance criteria.
2. **RFCs** document how each PRD requirement is implemented in this repo.
3. When the PRD changes, update the affected RFC(s), then code/schema/tests.
4. Update the **Status** column here when an RFC is completed or deferred.

## Recommended implementation order

001 → 002 → 003 → 004 → 012 → 005 → 006 → 007 + 009 → 008 → 011 → 010

Core P0–P2 pipeline RFCs (including RFC-012 momentum / z_score) are implemented. Remaining intentional ops items: temporary deploy `APP_ENV=dev`; remove manual `GCP_SA_KEY` after WIF is proven.
