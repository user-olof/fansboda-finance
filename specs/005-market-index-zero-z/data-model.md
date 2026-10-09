# Data Model: Market Index Z-Score Set to 0

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

No table or column change. Only `indices.z_score` on market rows changes value.

## `indices.z_score`

| Row kind | Identified by | Before | After |
|---|---|---|---|
| Market | `ticker` exactly `US-IDX`, `SWE-IDX`, `UK-IDX` | NULL | **0** |
| Sector | `ticker LIKE '%-IDX-%'` | `(m_s − mean) / pop. std` over the country's sector rows that week; NULL with < 2 sectors or std 0 | unchanged |

## Validation rules

- Market rows: `z_score = 0` always (also when market `momentum` is NULL).
- Sector mean and std are taken over sector rows only; market rows never contribute.
- After step 24: `SELECT count(*) FROM indices WHERE ticker IN ('US-IDX','SWE-IDX','UK-IDX') AND
  z_score IS DISTINCT FROM 0` = 0 (SC-001).

## State transition (stored market rows)

```text
NULL ──(step 24 / migrate_market_index_zero_z.sql)──▶ 0
0    ──(step 24 again)──▶ 0   (0 rows updated)
```
