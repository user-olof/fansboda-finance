# Contract: `README.md` outline and conventions

The public interface of this feature is the document itself. Section order and coverage are
fixed; wording is free.

## Outline

```text
# fansboda-finance
  intro paragraph (what / for whom / weekly / US, Sweden, UK / no UI or API / not advice)

## The mathematics
  ### Notation                      symbols used throughout (P, d, t, w, N, …)
  ### Weekly snapshot               one row per stock per calendar week; last trading day
  ### Simple moving averages        SMA-50, SMA-200; ≥ 200 closes
  ### Momentum                      SMA-50 / SMA-200; interpretation
  ### Weekly growth                 price, SMA-50, SMA-200 vs previous week, one adjusted history
  ### Market z-score                μ, population σ per market and week; when empty
  ### Outliers                      ×10 / −99.9 % rule; email; excluded from indices
  ### Equal-weighted indices
    #### Index names                market (NYSE & Nasdaq, OMX Stockholm, FTSE London) + sectors
    #### Daily returns and averaging
    #### Index level                 chained from 100; continued weekly from the last stored level
    #### Start date                  INDEX_START_DATE rule, 5 members, 250 days of history
    #### Index moving averages and momentum
    #### Weekly index row
    #### Members and uptrend
    #### Sector z-score
  ### When a value is empty         one table: measure → condition
  ### Worked examples               stock SMA/momentum, growth, z-score, index from 100

## Architecture
  short overview, one Mermaid flowchart
  bullets: data source · schedule · storage (3 country sets + indices) · jobs · one-off tools ·
           retention · outlier email · consumer
```

## Conventions

- Display math in ```` ```math ```` blocks; inline math as `` $`…`$ ``.
- Each formula followed by a one-sentence plain-language reading.
- Example windows that are shorter than 50 / 200 say so explicitly.
- Defaults are written as values with their setting name once, e.g. "2025-10-03
  (`INDEX_START_DATE`)".
- Architecture section ≤ ≈ 400 words plus the diagram (SC-003).
- Forbidden content (FR-007): connection strings, e-mail addresses, VM / zone / GCP project /
  service-account names, secret names' values, internal hostnames.
