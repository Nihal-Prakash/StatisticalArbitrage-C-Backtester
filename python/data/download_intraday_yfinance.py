"""Recent 15-minute Yahoo OHLCV. Keep datasets/raw for existing research consumers."""
import argparse
from collections import defaultdict
from datetime import timedelta
import json
import math
from pathlib import Path
import time
from typing import Any

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFException, YFRateLimitError

from _download_common import (ROOT, Summary, atomic_csv, atomic_json, check_output_directory,
                              consolidate_closes, load_tickers, normalize, read_existing, setup_logging)

INTERVAL = "15m"
TRANSIENT_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def normalize_symbol(batch: pd.DataFrame, symbol: str, allow_flat: bool = True) -> pd.DataFrame:
    if not isinstance(batch, pd.DataFrame) or batch.empty:
        raise ValueError("empty response")
    data = batch
    if isinstance(data.columns, pd.MultiIndex):
        for level in range(data.columns.nlevels):
            if symbol in data.columns.get_level_values(level):
                data = data.xs(symbol, axis=1, level=level)
                break
        else:
            raise ValueError("symbol missing from batch")
    elif not allow_flat:
        raise ValueError("ambiguous flat columns for multi-symbol response")
    data = data.rename_axis("date").reset_index()
    return normalize(data, intraday=True)


def signature(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def complete_session(existing: pd.DataFrame, session: pd.Timestamp) -> bool:
    expected = pd.date_range(session + pd.Timedelta(hours=9, minutes=15),
                             session + pd.Timedelta(hours=15, minutes=15), freq="15min")
    actual = pd.DatetimeIndex(existing.loc[existing.date.dt.date == session.date(), "date"])
    return actual.equals(expected.tz_convert(actual.tz))


def transient_failure(exc: Exception) -> bool:
    if isinstance(exc, YFRateLimitError):
        return True
    if isinstance(exc, YFException):
        return False
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", getattr(exc, "status_code", None))
    if status is not None:
        return status in TRANSIENT_STATUSES
    if isinstance(exc, OSError):
        return True
    # yfinance often converts both request failures and bad symbols into empty frames.
    return isinstance(exc, ValueError) and str(exc) in {"empty response", "no OHLC observations"}


def request_start(existing, path: Path, now: pd.Timestamp, days: int, force: bool):
    """None = current; 'period' = full request; ISO date = incremental overlap."""
    if force or existing is None:
        return "period"
    # Existing complete one-session files can be reused without metadata.
    if days == 1:
        session = None
        if now.dayofweek < 5 and now >= now.normalize() + pd.Timedelta(hours=15, minutes=30):
            session = now.normalize()
        elif now.dayofweek >= 5:
            session = now.normalize() - pd.Timedelta(days=now.dayofweek - 4)
        if session is not None and complete_session(existing, session):
            return None
    try:
        meta = json.loads(path.with_suffix(".meta.json").read_text())
        valid = (meta["signature"] == signature(path) and meta["provider"] == "yfinance"
                 and meta["interval"] == INTERVAL and meta["days"] == days)
        fetched = pd.Timestamp(meta["downloaded_at"])
        if valid and timedelta(0) <= now - fetched < timedelta(minutes=15):
            return None
        if valid and days == 1 and now.dayofweek >= 5:
            friday = now.normalize() - pd.Timedelta(days=now.dayofweek - 4)
            if fetched >= friday + pd.Timedelta(hours=15, minutes=30) \
                    and existing.date.max().date() == friday.date():
                return None
        if valid and (days == 1 or pd.Timestamp(meta["requested_start"]) <= now - pd.Timedelta(days=days) + pd.Timedelta(minutes=2)):
            return max(existing.date.max().normalize(), now.normalize() - pd.Timedelta(days=days - 1)).date().isoformat()
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return "period"


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--tickers", type=Path, default=ROOT / "python/tickers.json")
    cli.add_argument("--output", type=Path, default=ROOT / "datasets/raw")
    cli.add_argument("--consolidated", type=Path, default=ROOT / "datasets/intraday.csv")
    cli.add_argument("--log-dir", type=Path, default=ROOT / "datasets/logs")
    cli.add_argument("--days", type=int, default=1, help="Recent calendar days, 1–60; existing default: 1")
    cli.add_argument("--batch-size", type=int, default=50)
    cli.add_argument("--timeout", type=float, default=10)
    cli.add_argument("--retries", type=int, default=1, help="Retries for transient failures only, 0–2")
    cli.add_argument("--force", action="store_true")
    return cli


def run(args) -> int:
    logger = setup_logging("intraday", args.log_dir)
    symbols = load_tickers(args.tickers)
    if args.output.resolve() == (ROOT / "datasets/historical_daily").resolve():
        raise ValueError("intraday output cannot be the daily dataset directory")
    check_output_directory(args.output, intraday=True)
    summary = Summary(len(symbols), logger)
    now = pd.Timestamp.now(tz="Asia/Kolkata")
    logger.info("Loaded %d tickers from %s | yfinance %s | interval=%s | days=%d | batch=%d",
                len(symbols), args.tickers, yf.__version__, INTERVAL, args.days, args.batch_size)
    try:
        # Inspect and retain only this batch's existing data, not the universe.
        for offset in range(0, len(symbols), args.batch_size):
            batch = symbols[offset:offset + args.batch_size]
            groups = defaultdict(list)
            old = {}
            for symbol in batch:
                path = args.output / f"{symbol}.csv"
                old[symbol] = read_existing(path, intraday=True)
                start = request_start(old[symbol], path, now, args.days, args.force)
                if start is None:
                    summary.record(symbol, "skipped", "existing file current")
                else:
                    groups[start].append(symbol)
            logger.info("Batch %d/%d | %d symbols require download | %d current",
                        offset // args.batch_size + 1, (len(symbols) + args.batch_size - 1) // args.batch_size,
                        sum(map(len, groups.values())), len(batch) - sum(map(len, groups.values())))
            for start, pending in groups.items():
                options: dict[str, Any] = dict(interval=INTERVAL, auto_adjust=False, progress=False,
                               threads=True, group_by="ticker", ignore_tz=False, timeout=args.timeout)
                if start == "period" and args.days == 1:
                    options["period"] = "1d"
                else:
                    options["start"] = now - pd.Timedelta(days=args.days) + pd.Timedelta(minutes=1) if start == "period" else start
                    options["end"] = now
                began = time.monotonic()
                try:
                    downloaded = yf.download(pending, **options)
                    batch_error = ""
                    batch_exception = None
                except Exception as exc:
                    downloaded = None
                    batch_error = f"{type(exc).__name__}: {exc}"
                    batch_exception = exc
                # Successful symbols are saved before any failed symbol is retried.
                failures = []
                for symbol in pending:
                    try:
                        data = normalize_symbol(downloaded, symbol, allow_flat=len(pending) == 1)
                    except Exception as exc:
                        failures.append((symbol, batch_error or str(exc), batch_exception or exc))
                        continue
                    try:
                        save(data, old[symbol], args, symbol, now)
                        summary.record(symbol, "success", f"saved {len(data)} fetched rows | batch {time.monotonic()-began:.1f}s")
                    except Exception as exc:
                        summary.record(symbol, "failed", f"save failed: {type(exc).__name__}: {exc}")
                for symbol, reason, error in failures:
                    transient = transient_failure(error)
                    saved = False
                    for attempt in range(args.retries if transient else 0):
                        time.sleep(0.5 * (attempt + 1))
                        try:
                            data = normalize_symbol(yf.download([symbol], **options), symbol)
                            save(data, old[symbol], args, symbol, now)
                        except Exception as exc:
                            reason = f"{type(exc).__name__}: {exc}"
                            if not transient_failure(exc):
                                break
                        else:
                            summary.record(symbol, "success", f"saved {len(data)} fetched rows after retry")
                            saved = True
                            break
                    if not saved:
                        summary.record(symbol, "failed", reason + " | skipping")
    except KeyboardInterrupt:
        summary.interrupted = True
        logger.warning("Interrupted; completed CSVs remain intact")
    consolidate_closes(args.output, args.consolidated, symbols)
    return summary.finish(args.log_dir / "failed_intraday.json")


def save(data, existing, args, symbol, now):
    # Never merge incompatible daily files; normalization does not fabricate bars.
    merged = normalize(pd.concat([existing, data], ignore_index=True) if existing is not None else data,
                       intraday=True)
    path = args.output / f"{symbol}.csv"
    atomic_csv(merged, path)
    atomic_json({"provider": "yfinance", "interval": INTERVAL, "symbol": symbol,
                 "days": args.days, "requested_start": (now - pd.Timedelta(days=args.days)).isoformat(),
                 "requested_end": now.isoformat(), "downloaded_at": now.isoformat(),
                 "rows": len(merged), "signature": signature(path)}, path.with_suffix(".meta.json"))


def main() -> int:
    cli = parser()
    args = cli.parse_args()
    if not 1 <= args.days <= 60 or not 1 <= args.batch_size <= 100 or not math.isfinite(args.timeout) or args.timeout <= 0 or not 0 <= args.retries <= 2:
        cli.error("days must be 1–60, batch-size 1–100, timeout positive, retries 0–2")
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        cli.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
