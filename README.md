Statistical Arbitrage + C++ Backtester

Market data
-----------
Run commands from the repository root using the existing virtual environment.
Install/update dependencies with `.venv/bin/python -m pip install -r requirements.txt`.

Two primary downloaders use the canonical `python/tickers.json` universe:

* `.venv/bin/python python/data/download_intraday_yfinance.py`
  Yahoo 15-minute bars, 50-symbol batches with built-in threading. The existing
  one-day default and `datasets/raw/SYMBOL.NS.csv` location are preserved.
  Completed local ticker files are consolidated into `datasets/intraday.csv`.
  Use `--days 60` for the largest supported recent window. Yahoo does not provide
  arbitrary historical 15-minute data; requests stay just inside its 60-day cap.
* `.venv/bin/python python/data/download_historical_jugaad.py --start 2010-01-01`
  Daily NSE equities to `datasets/historical_daily/SYMBOL.NS.csv`. The `.NS`
  suffix is stripped only for the NSE request, never for the output filename.
  Completed local ticker files are consolidated into `datasets/historical.csv`.

`python/data/download_data.py` remains a compatibility entry point to the Yahoo
downloader, not a third implementation. The pre-existing files in raw were
intraday, so moving daily data there would silently change the research horizon.
The downloaders never intentionally mix frequencies in a directory.

CSV contract: `date,open,high,low,close,volume`, oldest first, one row per date or
timestamp. Intraday timestamps retain Asia/Kolkata offsets; daily dates are naive
midnight trading dates. Duplicate dates keep the last observation. Prices and
volume must be numeric and finite. Entirely empty OHLC rows are discarded; other
malformed rows fail validation. No forward/back filling or price imputation is
done here. Yahoo uses `auto_adjust=False`; NSE daily prices are unadjusted.
Corporate actions can therefore cause discontinuities: neither feed is an
adjusted-price total-return series.

Use `--help` for ticker file, output/log directories, timeouts and bounded retries.
`--force` bypasses output-completeness checks but still preserves good existing
observations outside the refreshed range. CSVs and metadata are written to
temporary files and atomically replaced. Failed/empty downloads do not erase
existing files. Avoid running two writers against the same output directory.

Yahoo only holds one batch in memory. Recent successful requests are reused for
15 minutes; complete legacy regular-session files can also be reused after close.
Updates overlap the latest stored session to refresh unfinished bars, then merge.
On Saturday/Sunday, a complete Friday session is treated as current. Exchange
holidays are not inferred without an exchange calendar, so a holiday may still
cause a bounded empty download attempt; no calendar dependency is added for that case.
Empty Yahoo responses get at most the configured retries, because the library
can hide network failures as empty data. Successful batch symbols are saved first.
An apparently valid provider response cannot prove that every market observation
is present; no missing bars are invented. Use `--force` for deliberate repair.

Historical downloads default to 2010-01-01 through yesterday (inclusive, India
time). One reusable worker owns the NSE session. Calendar-month requests keep
the request queue bounded, preserve Jugaad's persistent cache, and checkpoint
each successful chunk. No additional outer thread pool is used; the library's
worker count is restricted to one because its session/response state is shared.
This is intentionally conservative, not a claim that cold multi-year backfills
are fast. Start with the research range you actually need rather than blindly
backfilling the whole universe to 2010.

The HTTP timeout defaults to 10 seconds and an independent worker deadline to
`3*timeout+2` seconds per call. A stuck worker is terminated and replaced. After
`--symbol-timeout` seconds (default 180), no more chunks are scheduled for that
symbol; saved chunks resume on rerun. Transient timeouts, connections and selected
429/5xx errors receive at most `--retries` retries with small jittered backoff.
Schema, symbol and EQ-series errors fail without retries. A new symbol gets at
most two latest-chunk probes (to handle month-start holidays), then fails fast
rather than probing years of empty history. This can exclude suspended/delisted
symbols with older history.

Daily sidecars record successfully queried ranges, bound to the CSV's size/mtime,
including empty holiday/pre-listing chunks after valid data has been found.
With no trusted sidecar, only the actual observed dates are assumed present;
missing ranges are queried, not inferred from a weekday calendar. Newer dates
are fetched incrementally. The downloader uses `stock_raw()` rather than
`stock_df()` because the latter strips timezone information and silently coerces
some malformed numeric values in the inspected version. EQ filtering is explicit.
Jugaad's cache remains in its standard user cache directory unless `J_CACHE_DIR`
is set. `--force` ignores output checkpoints, not that provider cache; use a fresh
`J_CACHE_DIR` when intentionally checking for provider corrections. The existing
Bhavcopy cache is a different format and is neither rewritten nor treated as
proof of completion by these two provider-specific scripts.

`yfinance==1.7.0` and `jugaad-data==0.35.5` are pinned in `requirements.txt`.
The Yahoo batch/result behavior is version-sensitive, while the historical
worker intentionally accesses Jugaad's internal `h.s` session and `h.workers`.
Upgrade either provider only with the offline contract tests and live smoke tests.

Logs go to stdout and `datasets/logs/{intraday,historical}.log`; failed symbols
go to `failed_intraday.json` / `failed_historical.json` in that directory. Each
CSV has a `.meta.json` sidecar with provenance/completeness information, not extra
CSV rows. To retry a report, extract its `symbol` fields into a JSON list and pass
that list via `--tickers`. Exit codes: 0 complete, 1 per-symbol failures, 2 invalid
configuration/input, 130 interrupted. Ctrl+C retains completed files and prints
a partial summary; normal reruns resume them.

Research
--------
Run the local analysis steps after downloading:

    .venv/bin/python python/research/analyze_intraday.py
    .venv/bin/python python/research/analyze_historical.py
    .venv/bin/python python/research/analyze_pairs.py

The first two commands read `datasets/intraday.csv` and `datasets/historical.csv`
and write their correlation CSVs under `results/`. Pair selection lives in
`pairtickers.json`; pair analysis writes `results/normalizedprices.png` and
`results/stats.json`.

Offline tests (no Yahoo/NSE access):

    .venv/bin/python -m unittest discover -s python/data -v

Provider references:
* https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
* https://marketsetup.in/documentation/jugaad-data/
* https://github.com/jugaad-py/jugaad-data
