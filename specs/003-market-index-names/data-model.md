# Data Model: Rename the Market Indices

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

No table or column changes. Only the value of `indices.sector` on the three market rows changes.

## `indices` (existing, shared)

| Column | Market rows (`US-IDX`, `SWE-IDX`, `UK-IDX`) | Sector rows (`*-IDX-*`) |
|---|---|---|
| `ticker` | unchanged | unchanged |
| `sector` | **new label** (see below) | unchanged (sector name, e.g. `Technology`) |
| all other columns | unchanged | unchanged |

### Market labels

| `ticker` | `country` | Old `sector` | New `sector` |
|---|---|---|---|
| `US-IDX` | `us` | US Equity Index | NYSE & Nasdaq |
| `SWE-IDX` | `swe` | OMX Equity Index | OMX Stockholm |
| `UK-IDX` | `uk` | FTSE Equity Index | FTSE London |

### Validation rules

- A market row is identified by `ticker` exactly equal to one of the three market tickers; never by
  label and never by prefix (`US-IDX%` would include sector rows).
- After step 23: `SELECT count(*) FROM indices WHERE ticker IN ('US-IDX','SWE-IDX','UK-IDX') AND
  sector NOT IN ('NYSE & Nasdaq','OMX Stockholm','FTSE London')` = 0 (SC-001).
- Sector labels stay unique within a country and never equal a market label (FR-004).

## `IndexDefinition` (code, `equity_index.py`)

`INDEX_DEFINITIONS[country].name` is the single source of the market label; `ticker`, `country`,
and `currency` are unchanged. `sector_index_definition` is unchanged.

## State transition (stored market rows)

```text
old label ──(step 23 / migrate_rename_market_indices.sql)──▶ new label
new label ──(step 23 again)──▶ new label   (0 rows updated)
```
