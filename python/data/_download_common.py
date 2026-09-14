"""CSV/input boundary shared by the two downloaders; no provider logic."""
import csv
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def nse_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9&_-]*\.NS", symbol):
        raise ValueError(f"invalid NSE Yahoo symbol: {symbol!r}")
    return symbol.removesuffix(".NS")


def load_tickers(path: Path) -> list[str]:
    values = json.loads(path.read_text())
    if not isinstance(values, list) or not values:
        raise ValueError("ticker JSON must be a non-empty list of strings")
    symbols = []
    errors = []
    for index, value in enumerate(values):
        symbol = value.strip() if isinstance(value, str) else value
        try:
            nse_symbol(symbol)
        except ValueError as exc:
            errors.append(f"entry {index}: {exc}")
        else:
            symbols.append(symbol)
    if errors:
        raise ValueError("invalid ticker universe: " + "; ".join(errors[:10]))
    return list(dict.fromkeys(symbols))


def normalize(frame: pd.DataFrame, intraday: bool = False) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("empty response")
    data = frame.rename(columns=lambda c: str(c).strip().lower())
    if data.columns.duplicated().any():
        raise ValueError("duplicate columns")
    missing = set(COLUMNS) - set(data.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    data = data[COLUMNS].copy()
    data = data.dropna(subset=COLUMNS[1:5], how="all")
    if data.empty:
        raise ValueError("no OHLC observations")
    if pd.api.types.is_numeric_dtype(data["date"]):
        raise ValueError("numeric dates are not supported")
    # Naive provider dates/times mean exchange local time, never UTC.
    dates = pd.to_datetime(data.date, errors="coerce", format="mixed")
    if dates.isna().any():
        raise ValueError("malformed dates")
    try:
        if dates.dt.tz is not None:
            dates = dates.dt.tz_convert("Asia/Kolkata")
        elif intraday:
            dates = dates.dt.tz_localize("Asia/Kolkata")
        if intraday and ((dates == dates.dt.normalize()).any() or (dates.dt.minute % 15 != 0).any()
                         or (dates.dt.second != 0).any()):
            raise ValueError("expected 15-minute intraday timestamps, not daily dates")
        if not intraday:
            if dates.dt.tz is not None:
                dates = dates.dt.tz_localize(None)
            if (dates != dates.dt.normalize()).any():
                raise ValueError("intraday timestamps in daily data")
        data["date"] = dates
    except AttributeError as exc:
        raise ValueError("mixed or invalid timezones") from exc
    for column in COLUMNS[1:]:
        values = pd.to_numeric(data[column], errors="coerce")
        if not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"non-numeric/null {column}")
        data[column] = values
    if (data.volume < 0).any() or (data[COLUMNS[1:5]] <= 0).any().any():
        raise ValueError("non-positive prices or negative volume")
    if (data.high < data[["open", "close", "low"]].max(axis=1)).any() or (data.low > data[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("inconsistent OHLC bounds")
    return data.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def check_output_directory(path: Path, intraday: bool) -> None:
    """Check a single record per file so custom directories cannot mix frequencies."""
    for file in path.glob("*.csv"):
        try:
            with file.open(newline="") as handle:
                row = next(csv.DictReader(handle), None)
            if row:
                row = {str(key).strip().lower(): value for key, value in row.items()}
            if not row or not row.get("date"):
                continue  # Empty/malformed files are handled by read_existing.
            stamp = pd.Timestamp(row["date"])
            if pd.isna(stamp):
                continue
            if stamp.tzinfo is not None:
                stamp = stamp.tz_convert("Asia/Kolkata")
        except (ValueError, TypeError, csv.Error):
            continue
        if (stamp != stamp.normalize()) != intraday:
            raise ValueError(f"incompatible daily/intraday CSV in output directory: {file}")


def read_existing(path: Path, intraday: bool = False) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return normalize(pd.read_csv(path), intraday=intraday)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        logging.getLogger("download").warning("%s | invalid existing CSV: %s", path.stem, exc)
        return None


def _atomic(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    _atomic(path, lambda handle: frame.to_csv(handle, index=False))


def consolidate_closes(source: Path, destination: Path, symbols: list[str]) -> None:
    prices = {}
    for symbol in symbols:
        path = source / f"{symbol}.csv"
        if path.exists():
            prices[symbol] = pd.read_csv(path, usecols=["date", "close"], parse_dates=["date"]).set_index("date")["close"]
    if prices:
        frame = pd.DataFrame(prices).sort_index().ffill().bfill().rename_axis("date").reset_index()
        atomic_csv(frame, destination)


def atomic_json(value, path: Path) -> None:
    _atomic(path, lambda handle: json.dump(value, handle, indent=2))


def setup_logging(name: str, log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("download")
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in [logging.StreamHandler(sys.stdout), logging.FileHandler(log_dir / f"{name}.log")]:
        handler.setFormatter(logging.Formatter("%(levelname)-7s | %(message)s"))
        logger.addHandler(handler)
    return logger


class Summary:
    def __init__(self, total: int, logger: logging.Logger):
        self.total = total
        self.logger = logger
        self.success = 0
        self.skipped = 0
        self.failed = []
        self.started = time.monotonic()
        self.interrupted = False

    def record(self, symbol: str, status: str, reason: str = "") -> None:
        if status == "success":
            self.success += 1
        elif status == "skipped":
            self.skipped += 1
        elif status == "failed":
            self.failed.append({"symbol": symbol, "reason": reason})
        else:
            raise ValueError(status)
        self.logger.log(logging.WARNING if status == "failed" else logging.INFO,
                        "%s | %s | %s", symbol, status, reason)
        processed = self.success + self.skipped + len(self.failed)
        if processed % 25 == 0 or processed == self.total:
            self.logger.info("Progress %d/%d | success=%d skipped=%d failed=%d | elapsed=%.1fs",
                             processed, self.total, self.success, self.skipped, len(self.failed),
                             time.monotonic() - self.started)

    def finish(self, report_path: Path) -> int:
        atomic_json(self.failed, report_path)
        self.logger.info("================ Download Summary ================\n"
                         "Total: %d | Successful: %d | Already current: %d | Failed: %d\n"
                         "Unprocessed: %d | Interrupted: %s | Elapsed: %.1fs\n"
                         "Failure report: %s\n==================================================",
                         self.total, self.success, self.skipped, len(self.failed),
                         self.total - self.success - self.skipped - len(self.failed), self.interrupted,
                         time.monotonic() - self.started, report_path)
        return 130 if self.interrupted else int(bool(self.failed))
