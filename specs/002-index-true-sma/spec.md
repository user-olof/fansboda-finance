# Feature Specification: Index SMA-50 / SMA-200 as True Moving Averages of the Index Price

**Feature Branch**: `002-index-true-sma`

**Created**: 2026-10-08

**Status**: Draft

**Input**: User description: "SMA-50 and SMA-200 are incorrect. How do you recommend I calculate them?" — owner accepted the recommendation (2026-10-08): each week, rebuild the index's daily price from the member stocks' daily returns (reusing the weekly stock download), chain the weekly index price from those daily returns, and set SMA-50 / SMA-200 to the mean of the last 50 / 200 daily index levels, as for stocks; no new table.

**Builds on**: `specs/001-index-initial-sma` (start date, 100 base, initial SMA from the reconstructed daily index price, new-sector start, one-off initialization). This feature replaces 001's rule that weeks after the start date chain SMA-50 / SMA-200 from the members' stored weekly SMA growth (001 FR-007, FR-015, SC-005, User Story 3 scenario 1).

## Background

A stock's SMA-50 / SMA-200 is the mean of its last 50 / 200 daily closes, recomputed from scratch
every week. An index's SMA-50 / SMA-200 is currently only a true moving average on its start
date; after that each level is multiplied every week by one plus the members' average growth of
their own SMA-50 / SMA-200. The average growth of many stocks' SMAs is not the growth of the
moving average of the index's price, so the index SMAs drift away from a real moving average of
the index, and the error accumulates week after week.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Weekly index SMAs are true moving averages of the index price (Priority: P1)

As the owner reading the market and sector indices, I want every week's index SMA-50 and SMA-200
to be the average of the index's own daily price over the last 50 and 200 trading days, computed
the same way as for a stock, so that index momentum (SMA-50 / SMA-200) describes the index's real
trend and can be compared with the stocks' momentum.

Each week the index's daily price is rebuilt from its member stocks' daily price changes (equal
weight, outlier days excluded): it ends at the week's index price on the week's last trading day
and is worked backwards over the previous trading days. SMA-50 and SMA-200 are the averages of
the last 50 and 200 of those daily levels.

**Why this priority**: This is the reported defect; it affects every index row after the start
date and therefore momentum and the sector z-scores.

**Independent Test**: For a small set of stocks with known daily prices and a stored previous
index row, run the weekly index update and check that the new row's SMA-50 / SMA-200 equal the
averages of the last 50 / 200 daily index levels rebuilt backwards from the new week's price.

**Acceptance Scenarios**:

1. **Given** an index with a stored row for the previous week and member stocks with daily
   prices, **When** the weekly run adds a week, **Then** the new SMA-50 and SMA-200 equal the
   averages of the last 50 and 200 rebuilt daily index levels ending on the week's last trading
   day, to six decimals.
2. **Given** an index whose price is unchanged for 200 trading days, **When** the week is
   written, **Then** SMA-50 = SMA-200 = price and momentum = 1.
3. **Given** the same stocks and dates, **When** a stock's SMA is computed and a one-stock index
   of it is computed, **Then** the index's momentum equals the stock's momentum (to six decimals,
   apart from outlier days excluded from the index).

---

### User Story 2 - Weekly index price follows the daily index (Priority: P1)

As the owner, I want the weekly index price to move by the compounded equal-weighted daily
changes of its members since the previous stored index row, so that the price and its moving
averages come from one consistent daily series.

**Why this priority**: SMAs that are averages of one series and a price chained from another
would not be comparable; momentum and "price above SMA" would mix two definitions.

**Independent Test**: With a stored previous index row at price P and members whose
equal-weighted daily changes since then are known, the new week's price equals P times the
product of one plus each day's average change.

**Acceptance Scenarios**:

1. **Given** a stored index row at 105 for last week and two members that each rose 1% on one
   day this week and were flat otherwise, **When** the week is written, **Then** the price is
   105 × 1.01.
2. **Given** a week in which the weekly run did not run (missed Saturday), **When** the next run
   writes its week, **Then** the price is chained over every trading day since the last stored
   index row, so no change is lost or counted twice.
3. **Given** a week that is written again by a later run in the same week (a newer bar), **When**
   it is rewritten, **Then** the price is chained from the previous week's stored row, not from
   the row being replaced.

---

### User Story 3 - Initialization writes true SMAs for every stored week (Priority: P2)

**Depends on User Stories 1 and 2.**

As the owner, I want the one-off initialization to write every stored week, from the start date
to the latest week, with the same daily definition, so that the stored history is consistent
with what the weekly run writes from then on.

**Why this priority**: Already-stored rows carry the drifted SMAs until rebuilt; the rebuild is
run once per country after deploy.

**Independent Test**: Initialize a country; every stored index row's price equals the daily index
level on that row's date (100 on the start date) and its SMA-50 / SMA-200 equal the averages of
the last 50 / 200 daily levels ending on that date.

**Acceptance Scenarios**:

1. **Given** stored indices with drifted SMA levels, **When** the owner initializes a country,
   **Then** every index row of that country is rewritten with the daily definition and the start
   date still has price 100.
2. **Given** a new sector started by the weekly run (001 FR-016), **When** its rows are written,
   **Then** they use the same daily definition for every week from its start date.

---

### Edge Cases

- A member stock was skipped by this run's download because it already held the week's latest
  bar (a re-run in the same week): its daily prices are still needed for the index; they are
  downloaded for the index update so the index uses all members.
- A member's download failed: the daily averages use the members that were downloaded, and the
  run logs which ones were missing (as for the stock metrics).
- No member of an index has daily data for the week: no row is written for that index this week
  and a warning is logged; the next run chains over the missing days (User Story 2 scenario 2).
- A stock joined or left an index (new listing, sector change, removed ticker): the daily index
  is rebuilt with the current members, so the rebuilt past levels can differ slightly from the
  stored past prices; stored rows are not rewritten by the weekly run.
- A member's daily change above +900% (×10) or below −99.9%: excluded from that day's average
  (same limits as the weekly outlier check and 001 FR-003).
- Fewer than 200 daily levels are available for an index (very recent start): SMA-200 is the
  average of the levels available, and the run logs how many were used (as in 001).
- Splits and dividends: daily changes come from adjusted prices, so they do not show up as jumps.
- A trading day on which no member has data (exchange holiday): not part of the daily series.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: For every index row written after the start date, SMA-50 MUST equal the average of
  the index's daily levels over the 50 trading days ending on the row's trading date, and SMA-200
  the average over the 200 trading days ending on it.
- **FR-002**: The daily index levels MUST be rebuilt for each written week from the member
  stocks' adjusted daily closing prices: each day's change is the equal-weighted average of the
  members' daily changes that day (members with a price on that day and the day before),
  excluding changes above +900% or below −99.9%; the level on the row's trading date is the
  week's index price (FR-003), and each earlier level is the following level divided by one plus
  the following day's average change.
- **FR-003**: The weekly index price MUST equal the price of the index's latest stored row from an
  earlier week, multiplied by one plus the average daily change of every trading day after that
  row's trading date up to the week's last trading day.
- **FR-004**: Members MUST be the index's current member stocks (same country, sector, and
  eligibility as today), as in 001 FR-006.
- **FR-005**: The daily data MUST cover at least 200 trading days ending on the week's last
  trading day, plus every trading day since the previous stored index row. The weekly run MUST
  reuse the stock data it already downloads, widening that download as needed, and MUST download
  daily data only for members that this run did not download.
- **FR-006**: Momentum MUST stay SMA-50 / SMA-200; sector z-scores, stock count, and share in
  uptrend MUST stay computed as today.
- **FR-007**: The one-off initialization (001 FR-009) MUST write every stored week of an index
  from its start date with FR-001 to FR-003: price 100 on the start date, then each week's price
  chained by the daily changes, and each week's SMAs from the daily levels ending on that week's
  last trading day. The all-or-nothing rule per country (001) still applies.
- **FR-008**: A new sector index started by the weekly run (001 FR-016) MUST use the same daily
  definition for all of its weeks.
- **FR-009**: The weekly run MUST NOT rewrite index rows of earlier weeks; only the weeks it
  writes stock data for (and a new sector's weeks) are written.
- **FR-010**: The members' stored weekly growth numbers (price, SMA-50, SMA-200) MUST stay
  stored and MUST still drive the weekly outlier detection and email; they are no longer used to
  chain index levels.
- **FR-011**: Downloads MUST follow the project's download practice (batches, pauses, retries
  with backoff), and a failed batch MUST NOT stop the run.
- **FR-012**: Daily index levels are an intermediate result only; only weekly index rows are
  stored (no new table, no schema change).

### Key Entities

- **Index row**: one row per index per week with price, SMA-50, SMA-200, stock count, share in
  uptrend, momentum, and sector z-score (unchanged shape).
- **Daily index level**: the index's price on each trading day, rebuilt each week from the
  members' daily changes and ending at the week's price; used to compute the SMAs, not stored.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of index rows written by the weekly run or the initialization, SMA-50 and
  SMA-200 equal the averages of the last 50 and 200 rebuilt daily index levels, to six decimals.
- **SC-002**: The gap between an index's SMA-200 and a true 200-day average of its price no
  longer grows with the number of weeks since the start date: after one year, it is zero for
  rows written with the daily definition.
- **SC-003**: A normal weekly run downloads no more stock symbols than today (each member at most
  once); a re-run in the same week downloads only the members it needs for the index.
- **SC-004**: A normal weekly run finishes within the Saturday run window (well under one hour),
  and a full initialization of all three countries stays within it as well.
- **SC-005**: The start date keeps price 100 and the initial SMAs from 001 for 100% of indices.

## Assumptions

- The recommendation accepted on 2026-10-08 is the chosen approach; a stored daily index price
  table (migration step 23) was considered and not chosen.
- Rebuilding the daily levels with current members (FR-004) can make the rebuilt past levels
  differ slightly from stored past prices when membership changes; this is accepted as for 001.
- Data-provider revisions of adjusted prices (for example after dividends) can shift rebuilt past
  levels slightly between runs; this is accepted.
- The weekly price changes from "previous price × (1 + average weekly price growth)" (weekly
  rebalancing) to compounded average daily changes (daily rebalancing); the price series of a
  rebuilt index will therefore differ slightly from today's.
- Gap weeks no longer need a separate rule: the daily chain covers every trading day since the
  previous stored row.
- After deploy, the owner runs the one-off initialization for every country so stored history
  uses the daily definition; until then, old rows keep the drifted SMAs.
- The weekly job's download today covers about 300 calendar days (about 205 trading days); FR-005
  may require widening it (for example to about 400 calendar days); the cost stays inside the
  free tier (constitution II).
- No new infrastructure or cost; work stays inside the weekly batch or a manual rebuild
  (constitution I, II).
