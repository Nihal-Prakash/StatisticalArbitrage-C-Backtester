import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

import analyze_historical
import analyze_intraday
import analyze_pairs


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.results = self.root / "results"
        self.prices = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=4),
            "AAA.NS": [100, 102, 101, 104],
            "BBB.NS": [200, 201, 203, 206],
        })

    def test_analysis_output_paths(self):
        datasets = self.root / "datasets"
        datasets.mkdir()
        self.prices.to_csv(datasets / "intraday.csv", index=False)
        self.prices.to_csv(datasets / "historical.csv", index=False)

        analyze_intraday.analyze(datasets / "intraday.csv", self.results / "intraday_correlation.csv")
        analyze_historical.analyze(datasets / "historical.csv", self.results / "historical_correlation.csv")

        for name in ["intraday_correlation.csv", "historical_correlation.csv"]:
            result = pd.read_csv(self.results / name)
            self.assertEqual(list(result.columns), ["rank", "asset_a", "asset_b", "covariance", "correlation"])
            self.assertEqual(result.loc[0, ["asset_a", "asset_b"]].tolist(), ["AAA.NS", "BBB.NS"])

    def test_pair_analysis_output_paths(self):
        raw = self.root / "datasets/raw"
        raw.mkdir(parents=True)
        pair = self.root / "pairtickers.json"
        pair.write_text(json.dumps(["AAA.NS", "BBB.NS"]))
        for symbol in ["AAA.NS", "BBB.NS"]:
            self.prices[["date", symbol]].rename(columns={symbol: "close"}).to_csv(raw / f"{symbol}.csv", index=False)

        analyze_pairs.analyze(pair, raw, self.results)

        self.assertTrue((self.results / "normalizedprices.png").is_file())
        stats = json.loads((self.results / "stats.json").read_text())
        self.assertEqual((stats["asset_a"], stats["asset_b"]), ("AAA.NS", "BBB.NS"))
        self.assertEqual(stats["observations"], 3)

    def test_missing_correlation_input_fails_clearly(self):
        path = self.root / "datasets/intraday.csv"
        with self.assertRaisesRegex(FileNotFoundError, "datasets/intraday.csv.*not found"):
            analyze_intraday.analyze(path, self.results / "intraday_correlation.csv")


if __name__ == "__main__":
    unittest.main()
