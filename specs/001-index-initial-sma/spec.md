# Feature Specification: Index Initial SMA from Daily History

**Feature Branch**: `001-index-initial-sma`

**Created**: 2026-10-07

**Status**: Draft

**Input**: User description: "the initial values of sma_50 and sma_200 for indices are not correct. Base the calculation on the initial date for price (e.g. price = 100.00). Get the stock data from yfinance for the previous 250 trading days. Work out the price growths of the stocks backwards and then work out the index price for the 250 days prior to initial date. Then calculate the initial sma_50 and sma_200. All sma_50 and sma_200 after the initial date can be calculated with the price growths already in the DB, just like before."

**Amendment (2026-10-07)**: "add to 001 that the common start date is 2025-10-03. All indices should share this as a common start date."

**Amendment (2026-10-07)**: "I'd like to give a new sector the index price 100 and calculate sma_50 and sma_200 in the same way as we do it in compute_indices.py" — a new sector starts at 100 on its own first week, set up automatically by the weekly run (owner choices: weekly run with its own download; base on the sector's first week).

**Amendment (2026-10-08)**: "I'd like the code to check if at least 5 index components were listed on 25-10-03. Then use that as the start date of the new index. If less than 5 index components were listed at that date, then find the first date were there are at least 5 index components listed and use that date as the start date. Price on the start date is 100" — supersedes "base on the sector's first week" (FR-016).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Initial SMA levels are true moving averages of the index price (Priority: P1)

As the owner reading the market and sector indices, I want an index's SMA-50 and SMA-200 on the
common start date (where price = 100) to be the actual 50- and 200-trading-day averages of the
index's own price, so the first momentum value and every value chained from it describe the
index's real trend.

Today the initial SMA levels are set to 100 times the average of the member stocks'
SMA-to-price ratios. That is not a moving average of the index: it is pulled up or down by a few
stocks with extreme ratios, and because later weeks chain from it, the offset stays in the index
for its whole history.

Instead, the index price is reconstructed for the 250 trading days before the start date: the
member stocks' daily price changes over that period are averaged with equal weight, and the
index level is worked backwards from 100 on the start date. The initial SMA-50 is the average
of the last 50 of those daily levels (ending on the start date) and the initial SMA-200 the
average of the last 200.

**Why this priority**: This is the reported defect; it sets the starting point every later SMA
level and momentum value depends on.

**Independent Test**: For a small set of stocks with known daily prices, build an index and check
that the price on the start date is 100, the reconstructed daily levels follow the equal-weighted
average daily price change backwards from 100, and the initial SMA-50 / SMA-200 equal the
averages of the last 50 / 200 reconstructed levels.

**Acceptance Scenarios**:

1. **Given** an index and its member stocks on the start date, **When** the index is built,
   **Then** its price on the start date is 100 and its SMA-50 and SMA-200 equal the average of the
   reconstructed daily index levels over the 50 and 200 trading days ending on the start date.
2. **Given** two member stocks that each rose 1% on the last trading day before the start date,
   **When** the daily levels are reconstructed, **Then** the level one trading day earlier is
   100 / 1.01.
3. **Given** a sector index, **When** it is built, **Then** its daily history uses only that
   sector's member stocks, independently of the market index.

---

### User Story 2 - All indices share one start date, 2025-10-03 (Priority: P1)

As the owner comparing indices across countries and sectors, I want every market and sector
index to start at 100 on the same date, 2025-10-03, so that their levels are directly comparable:
an index at 110 has risen 10% since the same day as every other index at 110.

Today the US and Swedish indices start on 2025-10-03, but the UK indices start on 2025-07-25
because the UK history was backfilled further back. The one exception is an index with fewer
than 5 member stocks listed on 2025-10-03: it starts at 100 on the first later date on which at
least 5 are listed (FR-016).

**Why this priority**: Comparing indices is the point of having them side by side; differing
start dates make their levels incomparable.

**Independent Test**: Build or rebuild all indices; every index's level is anchored at 100 on
2025-10-03 and no index has stored rows dated before 2025-10-03.

**Acceptance Scenarios**:

1. **Given** UK stock data stored from 2025-07-21, **When** the UK indices are rebuilt, **Then**
   they are anchored at 100 on 2025-10-03 and have no rows dated before 2025-10-03.
2. **Given** a sector with fewer than 5 member stocks that have a price on 2025-10-03, **When**
   the owner initializes the indices, **Then** that sector index starts at 100 on the first
   week-end trading day on which at least 5 of its stocks have a price (FR-016), and does not block
   the other indices; a sector that never has 5 is skipped and logged.
3. **Given** the rows for 2025-10-03 have already been removed by retention, **When** the owner
   rebuilds the indices, **Then** the levels are still anchored at 100 on 2025-10-03 and match
   what they would have been had those rows still been stored.

---

### User Story 3 - Later weeks unchanged (Priority: P1)

As the owner, I want every week after the start date that has stored weekly stock data to keep
being calculated from that stored weekly growth data, exactly as today, so that only the
starting point changes and the weekly job needs no extra market-data downloads for existing
indices.

**Why this priority**: Required for the fix to be cheap and to keep weekly results consistent
with today's chaining rules.

**Independent Test**: Build an index with the new initial SMA levels, then add weeks; each later
week's SMA-50 and SMA-200 equal the previous week's level times one plus the members' average
stored weekly SMA growth, with the same outlier and gap-week rules as today.

**Acceptance Scenarios**:

1. **Given** an index with stored history, **When** the weekly run adds a week, **Then** no
   daily market data is downloaded for that index and its levels chain from the stored growth.
2. **Given** a sector that has no index yet, **When** the weekly run updates the indices,
   **Then** daily data is downloaded for that sector's stocks only, its start date is chosen as in
   FR-016 (2025-10-03 if at least 5 of its stocks have a price on that date, otherwise the first
   later week-end on which at least 5 do), the index is written at 100 on that date with
   SMA-50 / SMA-200 computed as in User Story 1, its rows for all later stored weeks are chained
   from stored growth, and the other indices' levels are unchanged.
3. **Given** a country with no index rows at all, **When** the weekly run updates the indices,
   **Then** no row is written for that country and a warning names the one-off initialization
   to run.

---

### User Story 4 - Rebuild existing indices with the corrected start (Priority: P2)

As the owner, I want to rebuild the stored indices for one country or all countries so that every
existing index gets the common start date, the corrected initial SMA levels, and a history
chained from them.

**Why this priority**: Already-stored indices carry the old starting values and, for the UK, the
old start date until rebuilt.

**Independent Test**: Rebuild a country; every index of that country is anchored at 100 on
2025-10-03 with the initial SMA levels from User Story 1, and later rows chain from them.

**Acceptance Scenarios**:

1. **Given** stored indices with the old initial SMA levels, **When** the owner rebuilds a
   country, **Then** every index of that country has the corrected initial SMA levels and all
   later weeks are recalculated from them.

---

### Edge Cases

- A member stock has fewer than 250 trading days of history before the start date (recent
  listing): it contributes to the daily average only on days where it has a price change.
- A trading day where no member stock has data (exchange holiday): the day is not part of the
  reconstructed series; holidays are taken from each country's own trading calendar.
- 2025-10-03 is not a trading day on some exchange: that country's indices use their last
  trading day on or before 2025-10-03 as the 100 base (2025-10-03 is a Friday and a trading day
  in the US, Sweden, and the UK).
- A member stock's daily price change above +900% (×10) or below −99.9%: excluded from that day's
  average, matching the weekly outlier limits.
- Splits and dividends inside the downloaded window: daily price changes come from adjusted
  prices, so they do not show up as jumps.
- Market data cannot be downloaded for some member stocks: the average uses the stocks that were
  downloaded, and the run logs which ones were missing.
- Market data cannot be downloaded for any member of an index that already has stored rows: the
  initialization leaves all of that country's indices unchanged (nothing deleted or written),
  logs which indices had no data, and ends with an error; other countries are initialized
  normally, and the owner's next run tries again. A sector with fewer than 5 stocks priced on the
  start date starts on its own later start date (FR-016) and does not block its country.
- An index never has 5 member stocks with a price on the same week-end: it gets no rows and the
  run logs it; the weekly run checks again every week.
- The weekly run cannot download data for a new sector's stocks: no row is written for that sector,
  a warning is logged, and the next weekly run tries again; the other indices are unaffected.
- Fewer than 200 reconstructed trading days are available for an index: the initial SMA-200 is
  the average of the days available, and the run logs how many were used.
- Retention has removed the weekly stock data for the start date and the weeks after it: the
  levels for the weeks between the start date and the oldest stored week are calculated from
  downloaded daily data with the same weekly rules (FR-014), so the 100 base on 2025-10-03 is
  kept.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every market and sector index MUST have price 100 on the common start date,
  2025-10-03 (FR-012), except an index with fewer than 5 member stocks priced on that date, which
  has price 100 on its own start date (FR-016).
- **FR-002**: When the owner rebuilds the indices (manual run, FR-009), the system MUST
  download daily adjusted closing prices for the index's member stocks covering the 250 trading
  days before the start date plus the start date.
- **FR-003**: For each trading day in that window, the system MUST compute each member stock's
  daily price change and the equal-weighted average of those changes over the stocks with data
  that day, excluding changes above +900% or below −99.9%.
- **FR-004**: The system MUST reconstruct the index's daily level backwards from 100 on the start
  date: the level on the previous trading day equals the level on the following trading day
  divided by one plus that following day's average change.
- **FR-005**: The initial SMA-50 MUST equal the average of the reconstructed levels over the 50
  trading days ending on the start date; the initial SMA-200 the average over the 200 trading
  days ending on the start date.
- **FR-006**: The members used for the reconstruction MUST be the stocks that belong to the index
  (same country and sector membership and eligibility as the weekly calculation) and have a price
  on the index's start date (FR-016).
- **FR-007**: Every week after the start date for which weekly stock data is stored MUST be
  calculated as today, by chaining each level with the members' average stored weekly growth
  (price, SMA-50, SMA-200) under the existing outlier and gap-week rules; no daily market data is
  downloaded for these weeks.
- **FR-008**: Momentum on the start date MUST equal the initial SMA-50 divided by the initial
  SMA-200, as for every other week.
- **FR-009**: Initializing the indices MUST be a separate one-off manual step, run by the owner
  for one country or all countries: it sets the start levels on the common start date (with the
  corrected initial SMA levels) and computes the full weekly time series from there. It is never
  scheduled and is not part of the weekly run.
- **FR-010**: Market-data downloads MUST follow the project's existing download practice
  (batched requests, pauses between batches, retries with backoff on rate limits and timeouts),
  and a failed batch MUST NOT stop the run.
- **FR-011**: The reconstructed daily levels are an intermediate result only; only weekly index
  rows are stored.
- **FR-012**: Every index with at least 5 member stocks priced on the common start date MUST start
  on that date, 2025-10-03. The common start date MUST be a single configuration setting
  (`INDEX_START_DATE`, default 2025-10-03) so the owner can move it, for example to the following
  week (2025-10-10), without a code change; the next initialization then uses the new date for
  every index. An index with fewer starts on its own start date (FR-016).
- **FR-013**: Indices MUST NOT have stored rows dated before the common start date; a rebuild MUST
  remove any such rows (for example the UK index rows from 2025-07-25 to 2025-09-26).
- **FR-014**: When weekly stock data between an index's start date and the oldest stored week is
  no longer stored (removed by retention), the one-off initialization, and the weekly run when it
  creates a new sector index (FR-016), MUST calculate the index levels for those weeks from downloaded daily data using the
  same weekly rules (equal-weighted weekly growth of price, SMA-50, and SMA-200 per member stock,
  outlier limits applied), so every index stays anchored at 100 on 2025-10-03. Weeks no longer
  inside the retention window are used for the calculation but not stored.
- **FR-015**: The weekly update of the indices MUST be part of the weekly run that fetches the
  stocks and computes their growth numbers: after the stocks' weekly growth is stored, it chains
  the new week's index price, SMA-50, and SMA-200 onto each index that already has stored rows
  (FR-007), and it MUST NOT download daily data for indices that have stored rows. A new sector
  index is started by the weekly run under FR-016. A country with no stored index rows at all
  gets no rows from the weekly run; the run logs a warning naming the one-off initialization to
  run.
- **FR-016**: When an index is created — by the one-off initialization, or by the weekly run for
  a sector with no stored rows (a new sector) — its start date (price 100) MUST be the common start
  date 2025-10-03 if at least 5 of its member stocks have a price on that date; otherwise the
  first later week-end trading day (a week's last trading day) on which at least 5 of its member
  stocks have a price. The minimum of 5 is a single project-wide setting. The initial SMA-50 /
  SMA-200 are computed on the start date exactly as in FR-002 to FR-006 and FR-008 (250 trading
  days before it). For a new sector the weekly run downloads daily data for that sector's stocks
  only and writes the sector's rows from its start week (or, when that week is no longer stored,
  from the oldest stored week with bridged levels, FR-014) through the latest week; the other
  indices' stored levels are not changed, only those weeks' sector z-scores are recomputed to
  include the new sector. An index that never has 5 member stocks priced on the same week-end
  gets no rows and is logged.

### Key Entities

- **Index**: a market index per country (US, SWE, UK) or a sector index per country and sector,
  stored as one row per week with price, SMA-50, SMA-200, stock count, share in uptrend,
  momentum, and sector z-score.
- **Common start date**: 2025-10-03, the date on which every index's price is 100 and its initial
  SMA levels are set, except indices with fewer than 5 member stocks priced on it, which start on their own start
  date (FR-016).
- **Reconstructed daily index level**: the index price for each of the 250 trading days before
  the start date, worked backwards from 100 using the members' average daily price change;
  used only to compute the initial SMA-50 and SMA-200.
- **Daily stock price history**: adjusted daily closing prices per member stock for the 250 days
  before the start date (and, when needed under FR-014, from the start date up to the oldest
  stored week), downloaded when an index is built.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of indices, the initial SMA-50 and SMA-200 equal the averages of the
  reconstructed daily index levels over the last 50 and 200 trading days, to six decimals.
- **SC-002**: 100% of indices with at least 5 member stocks priced on 2025-10-03 are anchored at
  100 on 2025-10-03; every other index has price 100 on the first later week-end on which at
  least 5 of its stocks are priced; 0 index rows are dated before 2025-10-03.
- **SC-003**: A small number of stocks with extreme price histories (for example one stock that
  fell 99% in the year before the start date) moves an index's initial SMA-200 by no more than
  its equal-weighted share of the daily changes, instead of dominating it.
- **SC-004**: A rebuild after retention has removed the start week gives the same levels, to six
  decimals, as a rebuild made while it was stored (apart from data-provider revisions).
- **SC-005**: Weekly levels after the start date are calculated with no additional market-data
  downloads for existing indices, so a normal weekly run takes no longer than it does today; only
  a week in which a new sector appears downloads daily data, for that sector's stocks only.
- **SC-006**: A full rebuild of all three countries' indices completes within the existing
  Saturday run window (well under one hour), within the data provider's rate limits.

## Assumptions

- "Just like before" means the existing chaining for weeks after the start date: each level
  moves by the members' average stored weekly growth of that measure (price, SMA-50, SMA-200).
- "Previous 250 trading days" means the 250 trading days before the start date, so 251 daily
  levels (including the start date) are available; SMA-200 needs only the last 200.
- 2025-10-03 is the oldest week all three countries have stored weekly stock data for
  (checked 2026-10-07: US and SWE from the week of 2025-09-29, UK from 2025-07-21).
- Retention (365 days) removes the 2025-10-03 week on the weekly run of 2026-10-10 and one more
  week every Saturday after that; stored index levels are not rebased when that happens (owner
  decision 2026-10-07), and FR-014 keeps rebuilds anchored on 2025-10-03.
- Daily data for indices is downloaded only by the one-off initialization and, in the weekly run,
  for the stocks of a new sector (FR-016); indices with stored rows never trigger a download
  (FR-015).
- An index with a later start date is not comparable in level with the indices based on
  2025-10-03. The start date depends only on when the members have prices, so a later one-off
  initialization gives the same start date (unless the membership changed).
- Every mention of 2025-10-03 as the common start date means the configured `INDEX_START_DATE`
  (default 2025-10-03). The setting should be a week's last trading day (normally a Friday), like
  2025-10-03. After changing it, the owner runs the one-off initialization for all countries so
  every index uses the same date; the weekly run only reads it.
- "Listed on a date" means the stock has a daily closing price on that date in the download.
  A later start date is always a week's last trading day, so the 100 base falls on the date of a
  weekly index row (2025-10-03 is itself a Friday). Confirmed by the owner 2026-10-08.
- The existing base-week SMA-to-price ratio limits (exclude ratios above 10 or below 0.001) no
  longer apply to the initial SMA levels, since they are no longer built from those ratios; the
  daily outlier limits in FR-003 take their place.
- Stock count and share in uptrend for a week are taken from the weekly data used for that week
  (stored, or downloaded under FR-014).
- Small revisions in the data provider's history can make a later rebuild differ slightly from
  an earlier one; this is acceptable.
- UK weekly stock data dated before 2025-10-03 is left to the normal retention purge; only
  index rows before the start date are removed.
- The one-off initialization is the `compute_indices.py` script (run manually, like the historical
  backfill); the weekly update lives in the weekly job `fetch_sma.py`, which no longer calls
  `compute_indices.py`.
- No new infrastructure or cost; work stays inside the weekly batch or a manual rebuild
  (constitution I, II).
