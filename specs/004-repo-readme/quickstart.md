# Quickstart: Validate the Front-Page Document

**Feature**: [spec.md](./spec.md) | Outline: [contracts/readme-outline.md](./contracts/readme-outline.md) |
Measures: [data-model.md](./data-model.md)

No database or network access is needed except the final GitHub render check.

## 1. Coverage (SC-001)

For every column in the data-model catalogue, find its definition section in `README.md`.
Expected: no column without a definition.

## 2. Numbers match the defaults (SC-005)

```bash
rg -n "DEFAULT_|SMA_50_WINDOW|SMA_200_WINDOW" config.py fetch_sma.py index_anchor.py
rg -n "50|200|365|9\.0|×10|99\.9|2025-10-03|250|NYSE|OMX Stockholm|FTSE London" README.md
```

Expected: every value in `README.md` equals the code default (research R4).

## 3. Nothing private (SC-004, FR-007)

```bash
rg -n -i "postgres(ql)?://|@[a-z0-9-]+\.[a-z]|gserviceaccount|fansboda-fetcher|us-central1|GCP_SA_KEY|project[-_ ]id|neon\.tech/.+/|\.iam\." README.md
```

Expected: no matches (links to public product homepages are fine).

## 4. Worked examples are correct (SC-002)

Recompute each example in a Python shell with the repository's own functions (do not commit the
snippet):

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run python
```

- SMA / momentum: `fetch_sma.compute_momentum` on the example SMAs; check the SMAs as plain means.
- Growth: `fetch_sma._growth(current, previous)`.
- Z-score: `statistics.pstdev` + `fetch_sma.compute_z_score`.
- Index: `index_anchor.daily_levels(averages, start, 100.0)` with the example's daily average
  returns (after dropping the outlier return).

Expected: results equal the document to the shown precision.

## 5. Rendering (spec edge case)

Push the branch and open `README.md` on GitHub (branch view). Expected: all ```` ```math ````
blocks, inline `` $`…`$ `` math, and the Mermaid diagram render; formulas are also readable in the
raw file.

## 6. Tests unaffected

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q
```

Expected: all pass (documentation-only change).
