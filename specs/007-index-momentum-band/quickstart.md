# Quickstart: Index Momentum Band for Member Stocks

## Unit tests (offline)

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q
```

Scenarios (see [data-model.md](./data-model.md)):

1. `weekly_momentum`: ratio on each week's last bar; `None` below 200 bars.
2. Returns of a stock are dropped in weeks with ratio 0.009 or 1.62, kept at exactly 0.15 / 1.5,
   kept with `None`; a stock at 0.9 then 0.1 then 0.9 is in, out, in.
3. Start-date minimum ignores out-of-band members (index starts later).
4. `BASE_WEEK_STATS_SQL` filters by the band with parameters; `write_index_weeks` passes them.
5. Config: defaults 0.15 / 1.5; env overrides; min ≥ max → `ValueError`.
6. All-in-band input → identical levels to before (SC-002).
7. Weekly path (`fold_index_history`, `_start_new_sectors`) passes the band.

## Manual check (dev database)

```bash
pipenv run python backfill_sma.py --country us        # if us_metrics is empty
pipenv run python compute_indices.py --country us
```

Expected: `Indices us: momentum band [0.15, 1.5] excluded …` and `Index band: excluded …`
lines (e.g. the US Consumer Defensive micro-caps near 0.01); `ticker_count` of
`US-IDX-CONSUMER-DEFENSIVE` drops by the number of excluded stocks in the latest week.

## Rollout

Deploy, then re-run `./scripts/run_compute_indices.sh` (us, swe, uk) on the VM. Log lines:
[contracts/settings-and-log.md](./contracts/settings-and-log.md).
