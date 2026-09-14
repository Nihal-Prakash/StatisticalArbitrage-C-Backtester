from pathlib import Path

from analyze_intraday import ROOT, correlate


def analyze(input_path: Path = ROOT / "datasets/historical.csv",
            output_path: Path = ROOT / "results/historical_correlation.csv") -> None:
    correlate(input_path, output_path)


if __name__ == "__main__":
    analyze()
