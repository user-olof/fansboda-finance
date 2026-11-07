# Contract: `fetch_sma.py` command line

```text
python fetch_sma.py [--trading_date YYYY-MM-DD]
```

| Option | Alias | Default | Meaning |
|---|---|---|---|
| `--trading_date YYYY-MM-DD` | `--trading-date` | today (UTC) | Run as of this date: fill its calendar week with each stock's last bar on or before it |

## Exit codes

| Case | Exit | Log |
|---|---|---|
| Success | 0 | `Running for trading_date=2026-10-23` (only with the option), then the usual lines and `Summary: …` |
| Malformed date | 2 | argparse usage error: `must be an ISO date (YYYY-MM-DD), got '2026/10/23'` |
| Future date | 1 | `ERROR --trading_date 2026-11-08 is in the future` |
| Older than retention | 1 | `ERROR --trading_date 2025-11-01 is older than the 365-day retention window (oldest 2025-11-07)` |
| Other failures | as today | as today |

Without the option the command, log, and exit codes are unchanged (Saturday cron).
