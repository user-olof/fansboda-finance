# Contract: Seed / Refresh Log Lines

Applies to `seed_tickers.py` (default mode) and `refresh_tickers.py`; the business summary mode
(`--update-business-summary`) is unchanged.

## Per ticker

```text
WARNING Discarded VOD.L: missing sector, industry
WARNING Discarded XYZ: missing company, sector, industry, market, exchange
WARNING Stored AAA.ST with missing exchange
ERROR   Failed to resolve metadata for BAD.ST          (followed by traceback; counted as discarded)
```

Field names, in this order: `symbol`, `company`, `sector`, `industry`, `market`, `exchange`.

## Per run

```text
INFO Ticker check: stored=540 discarded=31 warned=4
INFO Seeded 540 ticker(s) from tickers.txt (country=uk)     # unchanged format
```

- `Seeded N ticker(s) from` is parsed by `scripts/verify_dev_backfill.py`; its format MUST NOT
  change.
- Exit code: 0 when the run completes, regardless of discards (1 only for the existing errors:
  missing file, config, database failure).
