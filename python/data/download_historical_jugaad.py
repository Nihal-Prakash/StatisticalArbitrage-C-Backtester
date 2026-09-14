import argparse
import calendar
from datetime import date, datetime, timedelta
import hashlib
from io import StringIO
import json
import math
from pathlib import Path
import random
import signal
import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from jugaad_data.nse import bhavcopy_raw

from _download_common import (ROOT, atomic_csv, atomic_json, check_output_directory,
                              consolidate_closes, load_tickers, normalize, nse_symbol,
                              read_existing, setup_logging)

BHAVCOPY_COLUMNS = ["date", "symbol", "series", "open", "high", "low", "close", "volume", "isin"]
SCHEMAS = [
    {"TIMESTAMP": "date", "SYMBOL": "symbol", "SERIES": "series", "OPEN": "open",
     "HIGH": "high", "LOW": "low", "CLOSE": "close", "TOTTRDQTY": "volume", "ISIN": "isin"},
    {"TradDt": "date", "TckrSymb": "symbol", "SctySrs": "series", "OpnPric": "open",
     "HghPric": "high", "LwPric": "low", "ClsPric": "close", "TtlTradgVol": "volume",
     "ISIN": "isin"},
]
PROVIDER = "jugaad-data-bhavcopy"
LATEST_SCAN_DAYS = 14


class DateTimeout(TimeoutError):
    pass


def normalize_bhavcopy(raw, expected_date: date, logger=None) -> pd.DataFrame:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty bhavcopy response")
    try:
        frame = pd.read_csv(StringIO(raw), skipinitialspace=True)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError) as exc:
        raise ValueError(f"invalid bhavcopy CSV: {exc}") from exc
    frame.columns = [str(column).strip() for column in frame.columns]
    fields = next((schema for schema in SCHEMAS if set(schema).issubset(frame.columns)), None)
    if fields is None:
        raise ValueError(f"unsupported bhavcopy columns: {sorted(frame.columns)}")
    data = frame[list(fields)].rename(columns=fields)
    for column in ["symbol", "series", "isin"]:
        data[column] = data[column].fillna("").astype(str).str.strip()
    date_format = "%d-%b-%Y" if "TIMESTAMP" in fields else "%Y-%m-%d"
    dates = pd.to_datetime(data["date"], errors="coerce", format=date_format).dt.normalize()
    numeric = ["open", "high", "low", "close", "volume"]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = dates.notna() & dates.dt.date.eq(expected_date)
    valid &= data["symbol"].ne("") & data["series"].ne("")
    valid &= pd.Series(np.isfinite(data[numeric].to_numpy(dtype=float)).all(axis=1), index=data.index)
    valid &= data["volume"].ge(0) & data[["open", "high", "low", "close"]].gt(0).all(axis=1)
    valid &= data["high"].ge(data[["open", "low", "close"]].max(axis=1))
    valid &= data["low"].le(data[["open", "high", "close"]].min(axis=1))
    rejected = int((~valid).sum())
    if rejected and logger is not None:
        logger.warning("%s | rejected malformed bhavcopy rows=%d", expected_date, rejected)
    data = data.loc[valid].copy()
    if data.empty:
        raise ValueError("no valid bhavcopy rows")
    data["date"] = dates.loc[valid]
    return data[BHAVCOPY_COLUMNS].sort_values(
        ["date", "symbol", "series", "isin", "open", "high", "low", "close", "volume"],
        kind="mergesort").drop_duplicates().reset_index(drop=True)


def build_isin_map(frame: pd.DataFrame, symbols: list[str]):
    current = {nse_symbol(symbol): symbol for symbol in symbols}
    matches = frame.loc[frame["symbol"].isin(current) & frame["isin"].ne("")]
    candidates = {}
    unresolved = []
    for provider_symbol, ticker in current.items():
        isins = sorted(matches.loc[matches["symbol"].eq(provider_symbol), "isin"].unique())
        if len(isins) == 1:
            candidates[ticker] = isins[0]
        else:
            unresolved.append(ticker)
    result = {}
    conflicted = set()
    for ticker, isin in candidates.items():
        if isin in conflicted:
            unresolved.append(ticker)
        elif isin in result:
            unresolved.extend([result.pop(isin), ticker])
            conflicted.add(isin)
        else:
            result[isin] = ticker
    return result, list(dict.fromkeys(unresolved))


def map_rows(frame: pd.DataFrame, symbols: list[str], isin_map: dict[str, str]) -> pd.DataFrame:
    data = frame.loc[frame["series"].eq("EQ")].copy()
    canonical = set(symbols)
    direct = data["symbol"] + ".NS"
    data["ticker"] = direct.where(direct.isin(canonical))
    data["direct"] = data["ticker"].notna()
    data["ticker"] = data["ticker"].fillna(data["isin"].map(isin_map))
    data = data.dropna(subset=["ticker"])
    if data.empty:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    data = data.sort_values(["date", "ticker", "direct", "symbol"], kind="mergesort")
    data = data.drop_duplicates(["ticker", "date"], keep="last")
    return data[["ticker", "date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def month_ranges(start: date, end: date):
    while start <= end:
        right = min(end, start.replace(day=calendar.monthrange(start.year, start.month)[1]))
        yield start, right
        start = right + timedelta(days=1)


def days(start: date, end: date):
    while start <= end:
        yield start
        start += timedelta(days=1)


def error_reason(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:300]}"


def http_status(exc: Exception):
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def fetch_raw(day: date, timeout: float):
    def expired(signum, frame):
        raise DateTimeout(f"bhavcopy date deadline exceeded {timeout:g}s")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        return bhavcopy_raw(day)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def fetch_bhavcopy(day: date, timeout: float, retries: int, logger):
    for attempt in range(retries + 1):
        try:
            return "success", normalize_bhavcopy(fetch_raw(day, timeout), day, logger), ""
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            status = http_status(exc)
            reason = error_reason(exc)
            if isinstance(exc, requests.HTTPError) and status == 404:
                if attempt < retries:
                    logger.warning("%s | bhavcopy missing | confirming retry %d/%d", day, attempt + 1, retries)
                    time.sleep(0.5 * (attempt + 1) + random.uniform(0, 0.25))
                    continue
                logger.info("%s | no bhavcopy / non-trading day", day)
                return "unavailable", None, reason
            transient = isinstance(exc, (DateTimeout, requests.Timeout, requests.ConnectionError))
            transient |= isinstance(exc, requests.HTTPError) and (status == 429 or status is not None and status >= 500)
            if transient and attempt < retries:
                logger.warning("%s | transient bhavcopy failure | retry %d/%d", day, attempt + 1, retries)
                time.sleep(0.5 * (attempt + 1) + random.uniform(0, 0.25))
                continue
            logger.error("%s | bhavcopy unavailable after retries | %s", day, reason)
            return "failed", None, reason


def state_template(args, symbols):
    digest = hashlib.sha256("\n".join(symbols).encode()).hexdigest()
    return {"provider": PROVIDER, "start": args.start.isoformat(), "end": args.end.isoformat(),
            "tickers_sha256": digest, "latest_bhavcopy": None, "isin_map": {}, "unmapped": [],
            "completed_months": [], "processed_dates": [], "unavailable_dates": []}


def load_state(path: Path, args, symbols):
    expected = state_template(args, symbols)
    if args.force or not path.exists():
        return expected
    try:
        state = json.loads(path.read_text())
        for key in ["provider", "start", "end", "tickers_sha256"]:
            if state.get(key) != expected[key]:
                return expected
        if not isinstance(state.get("completed_months"), list):
            return expected
        if not isinstance(state.get("processed_dates"), list) or not isinstance(state.get("unavailable_dates"), list):
            return expected
        if not isinstance(state.get("isin_map"), dict) or not isinstance(state.get("unmapped"), list):
            return expected
        return state
    except (OSError, ValueError, TypeError):
        return expected


def find_latest(args, symbols, state, cache, logger):
    if state["latest_bhavcopy"] is not None:
        return state["isin_map"], state["unmapped"]
    for offset in range(LATEST_SCAN_DAYS):
        day = args.end - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        result = fetch_bhavcopy(day, args.timeout, args.retries, logger)
        cache[day] = result
        if result[0] == "success":
            isin_map, unresolved = build_isin_map(result[1], symbols)
            state["latest_bhavcopy"] = day.isoformat()
            state["isin_map"] = isin_map
            state["unmapped"] = unresolved
            atomic_json(state, args.log_dir / "historical_bhavcopy_state.json")
            logger.info("latest bhavcopy=%s | ISIN mappings=%d | unresolved=%d",
                        day, len(isin_map), len(unresolved))
            return isin_map, unresolved
    raise ValueError(f"no usable bhavcopy found in {LATEST_SCAN_DAYS}-day lookup window")


def merge_month(frame: pd.DataFrame, output: Path) -> int:
    if frame.empty:
        return 0
    updated = 0
    for ticker, rows in frame.groupby("ticker", sort=True):
        path = output / f"{ticker}.csv"
        fresh = normalize(rows.drop(columns="ticker"))
        existing = read_existing(path)
        merged = normalize(pd.concat([existing, fresh], ignore_index=True) if existing is not None else fresh)
        atomic_csv(merged, path)
        updated += 1
    return updated


def symbols_with_history(symbols, output: Path, start: date, end: date):
    usable = []
    for symbol in symbols:
        data = read_existing(output / f"{symbol}.csv")
        if data is not None and data["date"].dt.date.between(start, end).any():
            usable.append(symbol)
    return usable


def parser():
    cli = argparse.ArgumentParser(description="Download NSE EQ history from daily bhavcopies")
    cli.add_argument("--tickers", type=Path, default=ROOT / "python/tickers.json")
    cli.add_argument("--output", type=Path, default=ROOT / "datasets/historical_daily")
    cli.add_argument("--consolidated", type=Path, default=ROOT / "datasets/historical.csv")
    cli.add_argument("--log-dir", type=Path, default=ROOT / "datasets/logs")
    cli.add_argument("--start", type=date.fromisoformat, default=date(2010, 1, 1))
    cli.add_argument("--end", type=date.fromisoformat,
                     default=datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=1),
                     help="Inclusive; must be before today")
    cli.add_argument("--timeout", type=float, default=10, help="Wall-clock limit per bhavcopy date")
    cli.add_argument("--retries", type=int, default=1, help="Transient retries per date, 0–2")
    cli.add_argument("--force", action="store_true", help="Ignore completed-month checkpoints")
    return cli


def run(args):
    logger = setup_logging("historical", args.log_dir)
    symbols = load_tickers(args.tickers)
    if args.output.resolve() in {(ROOT / "datasets/raw").resolve(), (ROOT / "datasets/intraday_15m").resolve()}:
        raise ValueError("daily output cannot use an intraday dataset directory")
    check_output_directory(args.output, intraday=False)
    logger.info("Loaded %d tickers", len(symbols))
    logger.info("historical provider=jugaad-data bhavcopy")
    logger.info("range=%s through %s", args.start, args.end)
    began = time.monotonic()
    state_path = args.log_dir / "historical_bhavcopy_state.json"
    state = load_state(state_path, args, symbols)
    cache = {}
    processed = set(state["processed_dates"])
    unavailable = set(state["unavailable_dates"])
    failed = {}
    interrupted = False
    unresolved = state["unmapped"]
    ranges = list(month_ranges(args.start, args.end))
    try:
        isin_map, unresolved = find_latest(args, symbols, state, cache, logger)
        for index, (left, right) in enumerate(ranges, 1):
            month = left.strftime("%Y-%m")
            if month in state["completed_months"] and not args.force:
                logger.info("%s | checkpoint complete | skipping", month)
                logger.info("progress | months=%d/%d | elapsed=%.1fs", index, len(ranges), time.monotonic() - began)
                continue
            logger.info("%s | downloading bhavcopies", month)
            month_rows = []
            month_processed = set()
            month_unavailable = set()
            month_failed = False
            for day in days(left, right):
                if day.weekday() >= 5:
                    continue
                status, frame, reason = cache.get(day) or fetch_bhavcopy(day, args.timeout, args.retries, logger)
                if status == "success":
                    assert frame is not None
                    month_processed.add(day.isoformat())
                    mapped = map_rows(frame, symbols, isin_map)
                    if not mapped.empty:
                        month_rows.append(mapped)
                elif status == "unavailable":
                    month_unavailable.add(day.isoformat())
                else:
                    month_failed = True
                    failed[day.isoformat()] = {"date": day.isoformat(), "reason": reason}
            combined = pd.concat(month_rows, ignore_index=True) if month_rows else pd.DataFrame()
            updated = merge_month(combined, args.output)
            logger.info("%s | trading_days=%d | rows=%d", month, len(month_processed), len(combined))
            logger.info("%s | updated_symbols=%d", month, updated)
            processed.update(month_processed)
            unavailable.update(month_unavailable)
            if not month_failed:
                state["completed_months"] = sorted(set(state["completed_months"]) | {month})
                state["processed_dates"] = sorted(set(state["processed_dates"]) | month_processed)
                state["unavailable_dates"] = sorted(set(state["unavailable_dates"]) | month_unavailable)
                atomic_json(state, state_path)
            logger.info("progress | months=%d/%d | elapsed=%.1fs", index, len(ranges), time.monotonic() - began)
    except KeyboardInterrupt:
        interrupted = True
        logger.warning("Interrupted; completed monthly checkpoints remain intact")
    consolidate_closes(args.output, args.consolidated, symbols)
    usable = symbols_with_history(symbols, args.output, args.start, args.end)
    usable_set = set(usable)
    no_eq = [symbol for symbol in symbols if symbol not in usable_set]
    report = {"failed_dates": [failed[key] for key in sorted(failed)],
              "no_eq_history": no_eq, "unmapped": unresolved}
    atomic_json(report, args.log_dir / "failed_historical.json")
    requested = (args.end - args.start).days + 1
    weekends = sum(day.weekday() >= 5 for day in days(args.start, args.end))
    logger.info("requested_dates=%d | processed_trading_dates=%d | skipped_weekends=%d",
                requested, len(processed), weekends)
    logger.info("unavailable_weekdays=%d | failed_dates=%d", len(unavailable), len(failed))
    logger.info("usable_eq_symbols=%d | no_eq_history=%d | elapsed=%.1fs",
                len(usable), len(no_eq), time.monotonic() - began)
    return 130 if interrupted else int(bool(failed))


def main():
    cli = parser()
    args = cli.parse_args()
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    if args.start > args.end or args.end >= today:
        cli.error("start must not exceed end; end must be before today")
    if not math.isfinite(args.timeout) or args.timeout <= 0 or not 0 <= args.retries <= 2:
        cli.error("timeout must be finite and positive; retries must be 0–2")
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        cli.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
