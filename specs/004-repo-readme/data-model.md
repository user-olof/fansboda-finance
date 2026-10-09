# Data Model: Repository Front-Page Document

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

No database change. The "entities" are the document and the stored measures it must define. This
catalogue is the traceability table for SC-001: every row needs a definition in `README.md`.

## Document (`README.md`)

| Section | Content | Requirement |
|---|---|---|
| Introduction | What, for whom, weekly, three markets, no UI/API, not investment advice | FR-001, FR-009 |
| Mathematics | Stock measures → market statistics → outliers → indices → worked examples | FR-002–FR-004 |
| Architecture | Flow, schedule, storage, jobs, retention, email, consumer | FR-005 |

Outline and notation rules: [contracts/readme-outline.md](./contracts/readme-outline.md).

## Measures to define

### Per stock and week (`us_metrics` / `swe_metrics` / `uk_metrics`)

| Column | Definition section |
|---|---|
| `week_start`, `trading_date` | Weekly snapshot |
| `current_price` | Weekly snapshot (adjusted close on `trading_date`) |
| `sma_50`, `sma_200` | Simple moving averages |
| `momentum` | Momentum |
| `price_growth`, `sma_50_growth`, `sma_200_growth` | Weekly growth |
| `z_score` | Market z-score |
| `currency` | Weekly snapshot (trading currency) |

### Per market and week (`*_market_metrics`)

| Column | Definition section |
|---|---|
| `momentum_mean`, `momentum_std` | Market z-score (μ and population σ) |

### Per index and week (`indices`)

| Column | Definition section |
|---|---|
| `ticker`, `sector` (label) | Index names |
| `trading_date`, `current_price` | Index level, weekly row |
| `sma_50`, `sma_200` | Index moving averages |
| `momentum` | Index momentum |
| `ticker_count` | Members and uptrend |
| `pct_uptrend` | Members and uptrend |
| `z_score` | Sector z-score |
| `currency`, `country` | Index names |

### Not mathematical (architecture only)

`*_tickers` metadata (`company`, `sector`, `industry`, `market`, `exchange_name`,
`business_summary`), `updated_at`.

## Validation rules

- Every column above maps to a section heading in `README.md` (SC-001).
- Every number in `README.md` equals the current default (R4 table in research.md) (SC-005).
- No private identifier appears (quickstart §3) (SC-004).
