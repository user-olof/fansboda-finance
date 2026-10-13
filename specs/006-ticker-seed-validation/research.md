# Research: Ticker Seed Validation

## R1 — Where the check lives

**Decision**: A pure function `check_ticker_fields` in `seed_tickers.py` returns the missing
required fields and the missing warn-only fields for one resolved ticker.
`resolve_and_upsert_symbols` calls it per symbol and only appends complete tickers to the upsert
rows.

**Rationale**: `resolve_and_upsert_symbols` is the single path that stores tickers: both
`seed_tickers.py` and `refresh_tickers.py` (FR-007) go through it, and `upsert_tickers` is not
called anywhere else. A pure function keeps the rule unit-testable without mocks (constitution
VII), next to the existing pure `filter_symbols_for_country`.

**Alternatives considered**: Filtering in `db/tickers.upsert_tickers` — mixes a business rule
into the SQL layer and would hide discards from the caller's summary. A `NOT NULL` constraint on
the columns — a schema change that would also break stored incomplete rows (out of scope) and
turn a discard into a failed batch.

## R2 — Detecting "market missing"

**Decision**: `yfinance_client._watchlist_fields_from_info` returns the raw yfinance `market`
(`None` when absent) instead of the inferred one; `resolve_and_upsert_symbols` warns via the
check and stores `infer_listing_market(market=..., symbol=...)` as today. `_listing_market_from_info`
(its only caller) is removed, and its "inferring" warning is replaced by the seed check's warning.

**Rationale**: Today inference happens inside the yfinance helper, so the caller cannot tell a
provided market from an inferred one. Returning the raw value keeps I/O dumb and puts the rule in
one place; the stored value is unchanged (FR-004, routing and z-score grouping unaffected).
`resolve_watchlist_fields` has no other production caller.

**Alternatives considered**: Returning an extra `market_inferred` flag — widens a 6-tuple that
tests and callers unpack. Keeping the yfinance-level warning and adding the seed warning — logs
the same fact twice.

## R3 — Company-name warning in `yfinance_client`

**Decision**: Remove the `"No company name found for %s"` warning from
`_watchlist_fields_from_info`; the seed check reports missing company names as a discard.

**Rationale**: Avoid a duplicate log line per discarded ticker. `resolve_name` (the other user of
the helper) has no production caller.

## R4 — Failed lookups

**Decision**: A lookup that raises is logged with `logger.exception` (as today) and counted as
discarded; no row is stored (FR-003). The fallback row with only symbol and inferred market is
removed.

**Rationale**: That fallback row is exactly the incomplete ticker the feature excludes; it also
used to blank a stored row on refresh (FR-005).

## R5 — Logging and run summary

**Decision**:
- Discard: `WARNING Discarded <SYMBOL>: missing company, sector` (fields in fixed order symbol,
  company, sector, industry; then `market`, `exchange` when also missing).
- Warn-only: `WARNING Stored <SYMBOL> with missing market, exchange`.
- One summary line per call of `resolve_and_upsert_symbols`:
  `Ticker check: stored=N discarded=N warned=N`.
- The existing `Seeded %d ticker(s) from %s` line is kept unchanged; its count is now the
  number of stored rows.
- Return value stays the upsert row count (int), so `refresh_tickers.py` and `main` are unchanged;
  discards never change the exit code (FR-006).

**Rationale**: `scripts/verify_dev_backfill.py` parses `Seeded (\d+) ticker\(s\) from` and fails
on 0; keeping the line means the dev CI keeps working, and "0 stored" still flags a broken seed.

**Alternatives considered**: Returning a dataclass of counts — changes two callers and their
tests for no user benefit.

## R6 — Documentation

**Decision**: Update the `seed_tickers.py` row in `.cursor/rules/RULES.mdc` (incomplete tickers
discarded; missing market/exchange warned). `README.md` is not changed: RULES rule 6 covers
published formulas, windows, thresholds, defaults and index names, none of which change.
`project-docs/` untouched.
