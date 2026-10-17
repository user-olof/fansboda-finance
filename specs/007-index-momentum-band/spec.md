# Feature Specification: Index Momentum Band for Member Stocks

**Feature Branch**: `007-index-momentum-band`

**Created**: 2026-10-16

**Status**: Draft

**Input**: User description: "in compute indices, add a check on the SMA-50 / SMA-200 for stocks. The quotation must be within 0.15 to 1.5 or else the stock is to be excluded from the index."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stocks with an extreme SMA ratio do not move the indices (Priority: P1)

As the owner and as the consumer reading the indices, I want stocks whose SMA-50 / SMA-200
ratio (momentum) is below 0.15 or above 1.5 to be left out of the market and sector indices, so
that a handful of collapsed micro-caps, unadjusted reverse splits, or broken price series
(e.g. 17 US Consumer Defensive stocks below 0.5, several near 0.01) do not distort an index's
level, moving averages, member count, or uptrend percentage.

**Why this priority**: This is the whole feature; without it the indices keep including stocks
whose data is almost certainly unrepresentative.

**Independent Test**: Initialize a country's indices with a mocked set of member stocks where
some have a ratio below 0.15, some above 1.5, and some inside the band; the excluded stocks
contribute nothing to the index rows (level, SMA-50, SMA-200, member count, uptrend
percentage) in the weeks where their ratio is outside the band, and the included stocks give
the same result as today.

**Acceptance Scenarios**:

1. **Given** a stock with ratio 0.009 in a week, **When** the indices are computed, **Then** it
   is not a member of its market or sector index in that week.
2. **Given** a stock with ratio 1.62 in a week, **When** the indices are computed, **Then** it is
   not a member of its market or sector index in that week.
3. **Given** a stock with ratio exactly 0.15 or exactly 1.5, **When** the indices are computed,
   **Then** it is included (the band is inclusive).
4. **Given** a stock with ratio 0.98, **When** the indices are computed, **Then** it is included
   as today.
5. **Given** a stock at 0.9 in March and 0.1 in September, **When** the indices are computed,
   **Then** it is a member in March and excluded in September; when its ratio returns inside the
   band it is a member again.
6. **Given** the weekly update, **When** it writes the new week, **Then** the same rule applies
   as in the one-off initialization, so new weeks and rebuilt history follow one definition.
7. **Given** excluded stocks, **When** a run finishes, **Then** the log names how many stocks were
   excluded per country and lists them (symbol and ratio).

---

### User Story 2 - The band can be tuned without a code change (Priority: P2)

As the owner, I want the lower and upper limits (default 0.15 and 1.5) to be settings, like the
outlier limits, so that I can widen or narrow the band if it removes too many or too few stocks.

**Why this priority**: The defaults come from one look at the data; tuning should not need a
release.

**Independent Test**: Set the limits to other values and recompute; membership follows the new
limits.

**Acceptance Scenarios**:

1. **Given** no settings, **When** indices are computed, **Then** the band is 0.15 to 1.5.
2. **Given** limits set to 0.5 and 2.0, **When** indices are computed, **Then** a stock with ratio
   0.3 is excluded and one with ratio 1.8 is included.
3. **Given** a lower limit not below the upper limit, **When** the job starts, **Then** it stops
   with a clear configuration error.

---

### Edge Cases

- A stock without a ratio in a week (fewer than 200 trading days up to that week, so no
  SMA-200): not excluded by this rule in that week; it is handled as today.
- The history before the start date and weeks older than the retention window have no stored
  weekly metrics; the ratio for those weeks is still determined (FR-003) so the start-date
  averages follow the same rule.
- A stock that crosses the band mid-series simply leaves or rejoins; the index level carries on
  from the previous day (no jump from membership changes, since the index is built from daily
  returns).
- A sector where every stock falls outside the band in a week: that sector index gets no row for
  that week, as today when a sector has no stock with a positive price and SMAs.
- A sector whose remaining members drop below the start-date minimum (5): the start-date rule
  applies to the remaining members, so the sector index may start later or not at all.
- The stocks' own stored metrics (momentum, z-score, weekly growth) and the outlier email are
  unchanged; only index membership changes.
- Changing the band changes the published index definition; the stored history must be rebuilt
  for consistency (one-off initialization per country).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A stock whose SMA-50 / SMA-200 ratio is below the lower limit (default 0.15) or
  above the upper limit (default 1.5) MUST be excluded from its market index and its sector
  index; limits are inclusive (0.15 and 1.5 are inside).
- **FR-002**: An excluded stock MUST contribute neither to the index's daily returns (and thus its
  level, SMA-50, SMA-200, momentum, and sector z-score) nor to its member count or uptrend
  percentage.
- **FR-003**: Exclusion MUST be decided per stock per calendar week from the stock's ratio as
  of its last trading day in that week (the same definition as the published stock momentum).
  In a week where the ratio is outside the band the stock contributes nothing to that week's
  daily returns, member count, or uptrend percentage; in a week where it is inside the band it
  is a member. This applies to every week of the series, including the history before the start
  date, whether or not the week is still among the stored metrics.
- **FR-004**: The rule MUST apply both to the one-off index initialization and to the weekly
  index update (including new sector indices started by the weekly run), so stored history and
  new weeks follow one definition.
- **FR-005**: The lower and upper limits MUST be settings with defaults 0.15 and 1.5; a lower
  limit that is not below the upper limit MUST stop the run with a configuration error.
- **FR-006**: Each run MUST log the number of excluded stocks per country and the excluded
  symbols with their ratio.
- **FR-007**: A stock without a ratio in a week MUST NOT be excluded by this rule in that week.
- **FR-008**: The public front-page document and contributor guidance MUST describe the band and
  its defaults; the frozen baseline documents are not edited.
- **FR-009**: No change to stock metrics, market statistics, stock z-scores, the outlier email, or
  the database structure.

### Key Entities

- **Member stock**: a stock in the country's watchlist that belongs to the market index and (when
  it has a sector) one sector index; gains a membership condition: its SMA-50 / SMA-200 ratio is
  within the band.
- **Momentum band**: lower and upper limit (defaults 0.15, 1.5), inclusive.
- **Index row**: unchanged shape; its level, averages, member count, and uptrend percentage are
  computed from in-band members only.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After initialization and after each weekly update, 0 stocks whose ratio in that
  week is outside 0.15–1.5 are counted in that week's index member count.
- **SC-002**: For an index whose members are all inside the band, stored values are identical to
  before the change.
- **SC-003**: Every excluded stock appears in the run log with its ratio, and the logged count
  equals the number of excluded stocks.
- **SC-004**: Changing the limits through settings changes membership on the next run without a
  code change.
- **SC-005**: A stock that moves back inside the band is counted again from the first week it
  is inside.

## Assumptions

- "SMA-50 / SMA-200" is the stock's stored momentum, the same ratio published for stocks
  (README "Momentum"); "quotation" means this ratio.
- "Excluded from the index" covers the market index and the sector index, and all index fields
  (level, averages, momentum, member count, uptrend percentage, sector z-score).
- The band is inclusive and configurable like the outlier limits; defaults 0.15 and 1.5.
- The existing daily-return outlier filter (+900 % / −99.9 %) stays in place alongside the band.
- After deploy the owner re-runs the one-off initialization per country so stored history follows
  the new rule; from then on the weekly update keeps applying it.
- Clarified 2026-10-16: Q1 → both initialization and weekly update; Q2 → the ratio of each week
  (per-week exclusion), not the latest ratio and not a daily ratio.
- No schema change, new infrastructure, or cost (constitution I, II); indicators stay within
  SMA-50 / SMA-200 and their derived fields (constitution III).
