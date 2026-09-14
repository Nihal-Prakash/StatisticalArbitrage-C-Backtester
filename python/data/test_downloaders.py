"""Offline ingestion checks: .venv/bin/python -m unittest discover -s python/data -v"""
import json
from importlib.metadata import version
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from datetime import date
import time

import pandas as pd
from requests import HTTPError, Timeout
from yfinance.exceptions import YFTickerMissingError

import _download_common as common
import download_intraday_yfinance as intraday
import download_historical_jugaad as historical


def bars():
    return pd.DataFrame({
        "DATE": ["2026-09-08", "2026-09-07", "2026-09-08"],
        "OPEN": [10, 11, 12], "HIGH": [12, 13, 14],
        "LOW": [9, 10, 11], "CLOSE": [11, 12, 13], "VOLUME": [100, 200, 300],
    })


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_ticker_validation_and_order(self):
        path = self.root / "tickers.json"
        path.write_text(json.dumps([" TCS.NS ", "INFY.NS", "TCS.NS", "M&M.NS"]))
        self.assertEqual(common.load_tickers(path), ["TCS.NS", "INFY.NS", "M&M.NS"])
        self.assertEqual(common.nse_symbol("M&M.NS"), "M&M")
        for value in [None, {}, [None], [1], [""], ["TCS.NS.NS"], ["../TCS.NS"], ["TCS.ns"], ["TCS"]]:
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                common.load_tickers(path)
        path.write_text("{")
        with self.assertRaises(ValueError):
            common.load_tickers(path)
        with self.assertRaises(OSError):
            common.load_tickers(self.root / "absent.json")

    def test_normalization(self):
        result = common.normalize(bars())
        self.assertEqual(list(result.columns), common.COLUMNS)
        self.assertEqual(len(result), 2)
        self.assertTrue(result.date.is_monotonic_increasing)
        self.assertEqual(result.close.iloc[-1], 13)
        self.assertIsNone(result.date.dt.tz)
        for bad in [pd.DataFrame(), bars().drop(columns="CLOSE"), bars().assign(DATE="bad"), bars().assign(CLOSE="bad"), bars().assign(VOLUME="bad")]:
            with self.assertRaises(ValueError):
                common.normalize(bad)
        self.assertEqual(len(common.normalize(pd.concat([bars(), bars().assign(OPEN=None, HIGH=None, LOW=None, CLOSE=None)]))), 2)

    def test_timezone(self):
        data = bars().iloc[:1].assign(DATE="2026-09-07T18:30:00Z")
        self.assertEqual(str(common.normalize(data).date.iloc[0]), "2026-09-08 00:00:00")
        data = data.assign(DATE="2026-09-08T03:45:00Z")
        self.assertEqual(str(common.normalize(data, intraday=True).date.dt.tz), "Asia/Kolkata")

    def test_atomic_failure_preserves_file(self):
        path = self.root / "TCS.NS.csv"
        data = common.normalize(bars())
        common.atomic_csv(data, path)
        before = path.read_bytes()
        with patch.object(common.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                common.atomic_csv(data.iloc[:1], path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*.tmp")), [])
        self.assertEqual(len(common.read_existing(path)), 2)
        path.write_text("invalid")
        self.assertIsNone(common.read_existing(path))

    def test_yahoo_multiindex_and_empty_symbol(self):
        data = bars().rename(columns=str.title).rename(columns={"Date": "Datetime"}).set_index("Datetime")
        data.index = pd.to_datetime(data.index).tz_localize("Asia/Kolkata") + pd.Timedelta(hours=9, minutes=15)
        batch = pd.concat({"TCS.NS": data, "BAD.NS": data * float("nan")}, axis=1)
        self.assertEqual(len(intraday.normalize_symbol(batch, "TCS.NS")), 2)
        self.assertEqual(len(intraday.normalize_symbol(batch.swaplevel(axis=1), "TCS.NS")), 2)
        with self.assertRaises(ValueError):
            intraday.normalize_symbol(batch, "BAD.NS")
        with self.assertRaises(ValueError):
            intraday.normalize_symbol(batch, "MISSING.NS")


    def yahoo_args(self):
        tickers = self.root / "tickers.json"
        tickers.write_text(json.dumps(["TCS.NS", "BAD.NS", "INFY.NS", "TCS.NS"]))
        return intraday.parser().parse_args(["--tickers", str(tickers), "--output", str(self.root / "raw"),
                                            "--consolidated", str(self.root / "datasets/intraday.csv"),
                                            "--log-dir", str(self.root / "logs"), "--retries", "0"])

    def yahoo_frame(self):
        data = bars().rename(columns=str.title).rename(columns={"Date": "Datetime"}).set_index("Datetime")
        data.index = pd.to_datetime(data.index).tz_localize("Asia/Kolkata") + pd.Timedelta(hours=9, minutes=15)
        return pd.concat({"TCS.NS": data, "BAD.NS": data * float("nan"), "INFY.NS": data}, axis=1)

    def test_batch_failure_isolation_and_resume(self):
        args = self.yahoo_args()
        with patch.object(intraday.yf, "download", return_value=self.yahoo_frame()) as fetch:
            self.assertEqual(intraday.run(args), 1)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(fetch.call_args.args[0], ["TCS.NS", "BAD.NS", "INFY.NS"])
            self.assertEqual(fetch.call_args.kwargs["interval"], "15m")
            self.assertFalse(fetch.call_args.kwargs["auto_adjust"])
            self.assertTrue(fetch.call_args.kwargs["threads"])
        failed = json.loads((args.log_dir / "failed_intraday.json").read_text())
        self.assertEqual([x["symbol"] for x in failed], ["BAD.NS"])
        self.assertEqual(list(pd.read_csv(args.consolidated).columns), ["date", "TCS.NS", "INFY.NS"])
        for symbol in ["TCS.NS", "INFY.NS"]:
            self.assertEqual(len(pd.read_csv(args.output / f"{symbol}.csv", usecols=["date", "close"], parse_dates=["date"])), 2)
        with patch.object(intraday.yf, "download", return_value=pd.DataFrame()) as fetch:
            self.assertEqual(intraday.run(args), 1)
            self.assertEqual(fetch.call_args.args[0], ["BAD.NS"])

    def test_intraday_incremental_and_force(self):
        args = self.yahoo_args()
        data = intraday.normalize_symbol(self.yahoo_frame(), "TCS.NS")
        now = pd.Timestamp("2026-09-08T16:00:00+05:30")
        intraday.save(data, None, args, "TCS.NS", now)
        path = args.output / "TCS.NS.csv"
        self.assertIsNone(intraday.request_start(data, path, now, 1, False))
        self.assertEqual(intraday.request_start(data, path, now + pd.Timedelta(days=1), 1, False), "2026-09-09")
        self.assertEqual(intraday.request_start(data, path, now, 1, True), "period")
        self.assertEqual(intraday.request_start(data, path, now, 60, False), "period")
        path.write_text(path.read_text() + "\n")
        self.assertEqual(intraday.request_start(data, path, now, 1, False), "period")

    def test_intraday_weekend_freshness(self):
        args = self.yahoo_args()
        friday = pd.Timestamp("2026-09-11T16:00:00+05:30")
        dates = pd.date_range("2026-09-11 09:15", "2026-09-11 15:15", freq="15min",
                              tz="Asia/Kolkata")
        data = pd.DataFrame({"date": dates, "open": 10, "high": 12, "low": 9,
                             "close": 11, "volume": 100})
        data = data.iloc[:-1]
        intraday.save(data, None, args, "TCS.NS", friday)
        path = args.output / "TCS.NS.csv"
        for now in [pd.Timestamp("2026-09-12T12:00:00+05:30"),
                    pd.Timestamp("2026-09-13T12:00:00+05:30")]:
            self.assertIsNone(intraday.request_start(data, path, now, 1, False))
        path.with_suffix(".meta.json").unlink()
        self.assertIsNotNone(intraday.request_start(data, path,
                                                    pd.Timestamp("2026-09-12T12:00:00+05:30"), 1, False))

    def test_interrupt_and_failed_refresh_preserve_completed(self):
        args = self.yahoo_args()
        with patch.object(intraday.yf, "download", side_effect=KeyboardInterrupt):
            self.assertEqual(intraday.run(args), 130)
        with patch.object(intraday.yf, "download", return_value=self.yahoo_frame()):
            intraday.run(args)
        path = args.output / "TCS.NS.csv"
        before = path.read_bytes()
        args.force = True
        with patch.object(intraday.yf, "download", return_value=pd.DataFrame()):
            self.assertEqual(intraday.run(args), 1)
        self.assertEqual(path.read_bytes(), before)


    def test_frequency_directory_guard(self):
        common.atomic_csv(common.normalize(bars()), self.root / "TCS.NS.csv")
        common.check_output_directory(self.root, intraday=False)
        with self.assertRaises(ValueError):
            common.check_output_directory(self.root, intraday=True)

    def test_flat_batch_is_ambiguous(self):
        data = self.yahoo_frame()["TCS.NS"]
        with self.assertRaises(ValueError):
            intraday.normalize_symbol(data, "TCS.NS", allow_flat=False)
        self.assertEqual(len(intraday.normalize_symbol(data, "TCS.NS")), 2)


    def test_retry_only_failure_after_good_files_saved(self):
        args = self.yahoo_args()
        args.retries = 1
        batch = self.yahoo_frame()
        calls = []
        def fetch(symbols, **kwargs):
            calls.append(symbols)
            if len(calls) == 1:
                return batch
            self.assertTrue((args.output / "TCS.NS.csv").exists())
            self.assertTrue((args.output / "INFY.NS.csv").exists())
            return batch["TCS.NS"]
        with patch.object(intraday.yf, "download", side_effect=fetch), patch.object(intraday.time, "sleep"):
            self.assertEqual(intraday.run(args), 0)
        self.assertEqual(calls, [["TCS.NS", "BAD.NS", "INFY.NS"], ["BAD.NS"]])

    def test_yahoo_unexpected_save_exception_is_isolated(self):
        args = self.yahoo_args()
        args.tickers.write_text(json.dumps(["TCS.NS", "INFY.NS"]))
        original_save = intraday.save

        def save(data, existing, options, symbol, now):
            if symbol == "TCS.NS":
                raise RuntimeError("unexpected processing failure")
            return original_save(data, existing, options, symbol, now)

        with patch.object(intraday.yf, "download", return_value=self.yahoo_frame()), \
                patch.object(intraday, "save", side_effect=save):
            self.assertEqual(intraday.run(args), 1)
        self.assertFalse((args.output / "TCS.NS.csv").exists())
        self.assertTrue((args.output / "INFY.NS.csv").exists())
        failed = json.loads((args.log_dir / "failed_intraday.json").read_text())
        self.assertEqual(failed, [{"symbol": "TCS.NS", "reason":
                                   "save failed: RuntimeError: unexpected processing failure"}])

    def test_yahoo_transient_status_is_retried(self):
        args = self.yahoo_args()
        args.tickers.write_text(json.dumps(["TCS.NS"]))
        args.retries = 2
        transient = HTTPError("server busy", response=Mock(status_code=503))
        with patch.object(intraday.yf, "download",
                          side_effect=[transient, self.yahoo_frame()["TCS.NS"]]) as fetch, \
                patch.object(intraday.time, "sleep"):
            self.assertEqual(intraday.run(args), 0)
        self.assertEqual(fetch.call_count, 2)

    def test_yahoo_permanent_failure_is_not_retried(self):
        args = self.yahoo_args()
        args.tickers.write_text(json.dumps(["BAD.NS"]))
        args.retries = 2
        permanent = YFTickerMissingError("BAD.NS", "no timezone found")
        with patch.object(intraday.yf, "download", side_effect=permanent) as fetch, \
                patch.object(intraday.time, "sleep"):
            self.assertEqual(intraday.run(args), 1)
        fetch.assert_called_once()

    def test_provider_dependency_contract(self):
        requirements = (common.ROOT / "requirements.txt").read_text().splitlines()
        self.assertIn("yfinance==1.7.0", requirements)
        self.assertIn("jugaad-data==0.35.5", requirements)
        self.assertEqual(version("yfinance"), "1.7.0")
        self.assertEqual(version("jugaad-data"), "0.35.5")
        from jugaad_data.nse import bhavcopy_raw
        self.assertTrue(callable(bhavcopy_raw))

    def test_invalid_input_before_network(self):
        args = self.yahoo_args()
        args.tickers.write_text('["TCS.NS", null]')
        with patch.object(intraday.yf, "download") as fetch:
            with self.assertRaises(ValueError):
                intraday.run(args)
            fetch.assert_not_called()


    def test_legacy_session_skip_requires_all_bars(self):
        dates = pd.date_range("2026-09-08 09:15", "2026-09-08 15:15", freq="15min", tz="Asia/Kolkata")
        data = pd.DataFrame({"date": dates, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100})
        now = pd.Timestamp("2026-09-08T16:00:00+05:30")
        path = self.root / "TCS.NS.csv"
        self.assertIsNone(intraday.request_start(data, path, now, 1, False))
        self.assertEqual(intraday.request_start(data.drop(index=10), path, now, 1, False), "period")

    def historical_args(self, symbols=None, start="2026-09-08", end="2026-09-08", retries=0):
        tickers = self.root / "historical-tickers.json"
        tickers.write_text(json.dumps(symbols or ["TCS.NS", "INFY.NS"]))
        return historical.parser().parse_args([
            "--tickers", str(tickers), "--output", str(self.root / "daily"),
            "--consolidated", str(self.root / "datasets/historical.csv"),
            "--log-dir", str(self.root / "logs"), "--start", start, "--end", end,
            "--retries", str(retries)])

    def newer_bhavcopy(self, day, rows):
        return pd.DataFrame([
            {"TradDt": day.isoformat(), "TckrSymb": symbol, "SctySrs": series,
             "OpnPric": close - 1, "HghPric": close + 1, "LwPric": close - 2,
             "ClsPric": close, "TtlTradgVol": volume, "ISIN": isin}
            for symbol, series, isin, close, volume in rows
        ]).to_csv(index=False)

    def legacy_bhavcopy(self, day, rows):
        return pd.DataFrame([
            {"SYMBOL": symbol, "SERIES": series, "OPEN": close - 1,
             "HIGH": close + 1, "LOW": close - 2, "CLOSE": close,
             "TOTTRDQTY": volume, "TIMESTAMP": day.strftime("%d-%b-%Y").upper(),
             "ISIN": isin}
            for symbol, series, isin, close, volume in rows
        ]).to_csv(index=False)

    def test_bhavcopy_supplies_multiple_tickers_and_consolidates(self):
        args = self.historical_args()
        raw = self.newer_bhavcopy(args.end, [
            ("TCS", "EQ", "INE467B01029", 101, 1000),
            ("INFY", "EQ", "INE009A01021", 202, 2000)])
        with patch.object(historical, "bhavcopy_raw", return_value=raw) as fetch:
            self.assertEqual(historical.run(args), 0)
        fetch.assert_called_once_with(args.end)
        self.assertEqual(list(pd.read_csv(args.output / "TCS.NS.csv").columns), common.COLUMNS)
        self.assertEqual(list(pd.read_csv(args.consolidated).columns), ["date", "TCS.NS", "INFY.NS"])

    def test_bhavcopy_eq_filtering(self):
        day = date(2026, 9, 8)
        frame = historical.normalize_bhavcopy(self.newer_bhavcopy(day, [
            ("TCS", "EQ", "TCS-ISIN", 101, 1000),
            ("INFY", "BE", "INFY-ISIN", 202, 2000)]), day)
        mapped = historical.map_rows(frame, ["TCS.NS", "INFY.NS"], {})
        self.assertEqual(mapped.ticker.tolist(), ["TCS.NS"])

    def test_historical_weekend_skip(self):
        args = self.historical_args(start="2026-09-12", end="2026-09-13")
        friday = date(2026, 9, 11)
        raw = self.newer_bhavcopy(friday, [("TCS", "EQ", "TCS-ISIN", 101, 1000)])
        with patch.object(historical, "bhavcopy_raw", return_value=raw) as fetch:
            self.assertEqual(historical.run(args), 0)
        self.assertEqual([call.args[0] for call in fetch.call_args_list], [friday])

    def test_historical_non_trading_weekday(self):
        args = self.historical_args(start="2026-09-07", end="2026-09-08", retries=1)
        raw = self.newer_bhavcopy(args.end, [("TCS", "EQ", "TCS-ISIN", 101, 1000)])
        missing = HTTPError("not found", response=Mock(status_code=404))
        with patch.object(historical, "bhavcopy_raw", side_effect=[raw, missing, missing]), \
                patch.object(historical.time, "sleep"):
            self.assertEqual(historical.run(args), 0)
        state = json.loads((args.log_dir / "historical_bhavcopy_state.json").read_text())
        self.assertEqual(state["unavailable_dates"], ["2026-09-07"])
        self.assertEqual(state["processed_dates"], ["2026-09-08"])

    def test_historical_missing_confirmation_can_recover(self):
        day = date(2026, 9, 8)
        raw = self.newer_bhavcopy(day, [("TCS", "EQ", "TCS-ISIN", 101, 1000)])
        missing = HTTPError("not found", response=Mock(status_code=404))
        with patch.object(historical, "bhavcopy_raw", side_effect=[missing, raw]), \
                patch.object(historical.time, "sleep"):
            status, frame, reason = historical.fetch_bhavcopy(day, 10, 1, Mock())
        self.assertEqual(status, "success")
        assert frame is not None
        self.assertEqual(frame.symbol.tolist(), ["TCS"])
        self.assertEqual(reason, "")

    def test_historical_transient_retry(self):
        args = self.historical_args(retries=1)
        raw = self.newer_bhavcopy(args.end, [("TCS", "EQ", "TCS-ISIN", 101, 1000)])
        with patch.object(historical, "bhavcopy_raw", side_effect=[Timeout("slow"), raw]) as fetch, \
                patch.object(historical.time, "sleep"):
            self.assertEqual(historical.run(args), 0)
        self.assertEqual(fetch.call_count, 2)

    def test_historical_date_timeout(self):
        started = time.monotonic()
        with patch.object(historical, "bhavcopy_raw", side_effect=lambda day: time.sleep(1)):
            with self.assertRaises(historical.DateTimeout):
                historical.fetch_raw(date(2026, 9, 8), 0.01)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_historical_failed_date_does_not_stop_later_date(self):
        args = self.historical_args(start="2026-09-07", end="2026-09-08")
        raw = self.newer_bhavcopy(args.end, [("TCS", "EQ", "TCS-ISIN", 101, 1000)])
        with patch.object(historical, "bhavcopy_raw", side_effect=[raw, RuntimeError("broken API")]):
            self.assertEqual(historical.run(args), 1)
        self.assertTrue((args.output / "TCS.NS.csv").exists())
        report = json.loads((args.log_dir / "failed_historical.json").read_text())
        self.assertEqual([item["date"] for item in report["failed_dates"]], ["2026-09-07"])

    def test_legacy_bhavcopy_normalization(self):
        day = date(2024, 7, 5)
        result = historical.normalize_bhavcopy(
            self.legacy_bhavcopy(day, [("TCS", "EQ", "TCS-ISIN", 101, 1000)]), day)
        self.assertEqual(list(result.columns), historical.BHAVCOPY_COLUMNS)
        self.assertEqual(result.iloc[0].to_dict(), {
            "date": pd.Timestamp(day), "symbol": "TCS", "series": "EQ", "open": 100,
            "high": 102, "low": 99, "close": 101, "volume": 1000, "isin": "TCS-ISIN"})

    def test_newer_bhavcopy_normalization(self):
        day = date(2024, 7, 8)
        result = historical.normalize_bhavcopy(
            self.newer_bhavcopy(day, [("INFY", "EQ", "INFY-ISIN", 202, 2000)]), day)
        self.assertEqual(result.symbol.tolist(), ["INFY"])
        self.assertEqual(result.close.tolist(), [202])

    def test_current_symbol_match_precedes_isin(self):
        day = date(2026, 9, 8)
        frame = historical.normalize_bhavcopy(
            self.newer_bhavcopy(day, [("TCS", "EQ", "360-ISIN", 101, 1000)]), day)
        mapped = historical.map_rows(frame, ["TCS.NS", "360ONE.NS"], {"360-ISIN": "360ONE.NS"})
        self.assertEqual(mapped.ticker.tolist(), ["TCS.NS"])

    def test_isin_rename_mapping(self):
        day = date(2024, 7, 5)
        latest_day = date(2026, 9, 8)
        latest = historical.normalize_bhavcopy(self.newer_bhavcopy(
            latest_day, [("360ONE", "EQ", "INE466L01038", 101, 1000)]), latest_day)
        isin_map, unresolved = historical.build_isin_map(latest, ["360ONE.NS"])
        old = historical.normalize_bhavcopy(
            self.legacy_bhavcopy(day, [("IIFLWAM", "EQ", "INE466L01038", 202, 2000)]), day)
        self.assertEqual(unresolved, [])
        self.assertEqual(historical.map_rows(old, ["360ONE.NS"], isin_map).ticker.tolist(), ["360ONE.NS"])

    def test_unmapped_security_is_ignored(self):
        day = date(2026, 9, 8)
        frame = historical.normalize_bhavcopy(
            self.newer_bhavcopy(day, [("OUTSIDE", "EQ", "OUTSIDE-ISIN", 101, 1000)]), day)
        self.assertTrue(historical.map_rows(frame, ["TCS.NS"], {}).empty)

    def test_historical_monthly_checkpoint_resume(self):
        args = self.historical_args()
        raw = self.newer_bhavcopy(args.end, [("TCS", "EQ", "TCS-ISIN", 101, 1000)])
        with patch.object(historical, "bhavcopy_raw", return_value=raw) as first:
            self.assertEqual(historical.run(args), 0)
        with patch.object(historical, "bhavcopy_raw") as second:
            self.assertEqual(historical.run(args), 0)
        first.assert_called_once()
        second.assert_not_called()
        state = json.loads((args.log_dir / "historical_bhavcopy_state.json").read_text())
        self.assertEqual(state["completed_months"], ["2026-09"])

    def test_interrupted_month_is_safely_reprocessed(self):
        args = self.historical_args(start="2026-09-07", end="2026-09-08")
        latest = self.newer_bhavcopy(args.end, [("TCS", "EQ", "TCS-ISIN", 102, 1000)])
        with patch.object(historical, "bhavcopy_raw", side_effect=[latest, KeyboardInterrupt]):
            self.assertEqual(historical.run(args), 130)
        state = json.loads((args.log_dir / "historical_bhavcopy_state.json").read_text())
        self.assertEqual(state["completed_months"], [])
        monday = self.newer_bhavcopy(date(2026, 9, 7), [("TCS", "EQ", "TCS-ISIN", 101, 1000)])
        with patch.object(historical, "bhavcopy_raw", side_effect=[monday, latest]) as fetch:
            self.assertEqual(historical.run(args), 0)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(pd.read_csv(args.output / "TCS.NS.csv")), 2)

    def test_historical_rerun_does_not_duplicate_dates(self):
        args = self.historical_args(symbols=["TCS.NS"])
        raw = self.newer_bhavcopy(args.end, [("TCS", "EQ", "TCS-ISIN", 101, 1000)])
        with patch.object(historical, "bhavcopy_raw", return_value=raw):
            self.assertEqual(historical.run(args), 0)
            args.force = True
            self.assertEqual(historical.run(args), 0)
        self.assertEqual(len(pd.read_csv(args.output / "TCS.NS.csv")), 1)

    def test_historical_atomic_failure_preserves_existing_file(self):
        args = self.historical_args(symbols=["TCS.NS"])
        path = args.output / "TCS.NS.csv"
        common.atomic_csv(common.normalize(bars()), path)
        before = path.read_bytes()
        raw = self.newer_bhavcopy(args.end, [("TCS", "EQ", "TCS-ISIN", 101, 1000)])
        with patch.object(historical, "bhavcopy_raw", return_value=raw), \
                patch.object(historical, "atomic_csv", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                historical.run(args)
        self.assertEqual(path.read_bytes(), before)

    def test_non_eq_ticker_is_not_provider_failure(self):
        args = self.historical_args(symbols=["3IINFOLTD.NS"])
        raw = self.newer_bhavcopy(args.end, [("3IINFOLTD", "BE", "INE748C01038", 101, 1000)])
        with patch.object(historical, "bhavcopy_raw", return_value=raw):
            self.assertEqual(historical.run(args), 0)
        report = json.loads((args.log_dir / "failed_historical.json").read_text())
        self.assertEqual(report["failed_dates"], [])
        self.assertEqual(report["no_eq_history"], ["3IINFOLTD.NS"])


    def test_intraday_rejects_daily_and_malformed_prices(self):
        with self.assertRaises(ValueError):
            common.normalize(bars(), intraday=True)
        with self.assertRaises(ValueError):
            common.normalize(bars().assign(HIGH=1))
        with self.assertRaises(ValueError):
            common.normalize(bars().assign(DATE=0))
        common.atomic_csv(bars(), self.root / "TCS.NS.csv")
        with self.assertRaises(ValueError):
            common.check_output_directory(self.root, intraday=True)


if __name__ == "__main__":
    unittest.main()
