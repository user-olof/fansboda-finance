# Quickstart: Weekly Fetch for a Missed Trading Date

## Unit tests (offline)

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q
```

Scenarios:

1. `download_batch(..., end=D)` passes `D + 1 day` to yfinance; without `end`, none.
2. `resolve_run_date`: none → today; past date → that date; future / older than retention →
   `ValueError`.
3. Parser accepts `--trading_date` and `--trading-date`; a malformed date exits with a usage error.
4. `main(["--trading_date", D])`: freshness check with `today=D`, download from `D − 600 days`
   to `D`, missing index members downloaded to `D`, index update for `D`'s week.
5. `main(["--trading_date", <future>])` exits 1 without loading tickers.
6. `main()` without the option behaves as before (existing tests).

## Filling missed weeks in production

On the VM, as `fansboda`, one run per missed week (oldest first; any day of the week, the Friday
is natural):

```bash
cd /opt/fansboda-finance
for d in 2026-10-23 2026-10-30; do
  sudo -u fansboda bash -c "set -a; . ./.env; set +a; PIPENV_VENV_IN_PROJECT=1 pipenv run python fetch_sma.py --trading_date $d"
done
```

Expected: `Running for trading_date=…`, `Summary: … inserted=N …` with N ≈ number of tickers, and
`Indices: wrote … row(s) from week(s) <that Monday>`. Re-running the same date skips every stock
(`Skipping … already holding the latest bar`).

Check (read-only):

```sql
SELECT week_start, COUNT(*) FROM us_metrics WHERE week_start >= '2026-10-12' GROUP BY 1 ORDER BY 1;
SELECT trading_date, COUNT(*) FROM indices WHERE country = 'us' AND trading_date >= '2026-10-12' GROUP BY 1 ORDER BY 1;
```

Contract: [contracts/cli.md](./contracts/cli.md).
