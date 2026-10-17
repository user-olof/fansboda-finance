# Contract: Momentum Band Settings and Log Lines

## Settings (`.env` / environment)

```text
INDEX_MOMENTUM_MIN=0.15   # default; must be > 0
INDEX_MOMENTUM_MAX=1.5    # default; must be > INDEX_MOMENTUM_MIN
```

Invalid values → `ERROR INDEX_MOMENTUM_MIN must be below INDEX_MOMENTUM_MAX …`, exit 1, nothing
written.

## Log lines (`compute_indices.py`, `fetch_sma.py`)

```text
INFO    Indices us: momentum band [0.15, 1.5] excluded 912 stock-week(s) from 41 stock(s)
WARNING Index band: excluded PAVS week 2026-10-12 ratio 0.009
```

- Weekly run: one WARNING per stock excluded in the week(s) written.
- Initialization: WARNING lines for the latest stored week only; the INFO summary counts every
  week.
- Existing lines (`Summary: …`, `Indices <c>: series=…`, outlier lines) unchanged.
