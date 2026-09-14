import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def analyze(pair_path: Path = ROOT / "python/pairtickers.json",
            data_dir: Path = ROOT / "datasets/raw",
            results_dir: Path = ROOT / "results/exploration") -> None:
    symbol_a, symbol_b = json.loads(pair_path.read_text())

    a = pd.read_csv(data_dir / f"{symbol_a}.csv", parse_dates=["date"])
    b = pd.read_csv(data_dir / f"{symbol_b}.csv", parse_dates=["date"])

    frame = pd.merge(
        a[["date", "close"]],
        b[["date", "close"]],
        on="date",
        how="inner",
        suffixes=("_a", "_b")
    ).sort_values("date")

    frame["ret_a"] = np.log(frame["close_a"] / frame["close_a"].shift(1))
    frame["ret_b"] = np.log(frame["close_b"] / frame["close_b"].shift(1))
    frame = frame.dropna()
    frame["norm_a"] = 100 * frame["close_a"] / frame["close_a"].iloc[0]
    frame["norm_b"] = 100 * frame["close_b"] / frame["close_b"].iloc[0]

    stats = {
        "asset_a": symbol_a,
        "asset_b": symbol_b,
        "observations": len(frame),
        "mean_return_a": frame["ret_a"].mean(),
        "mean_return_b": frame["ret_b"].mean(),
        "std_return_a": frame["ret_a"].std(),
        "std_return_b": frame["ret_b"].std(),
        "covariance": frame["ret_a"].cov(frame["ret_b"]),
        "return_correlation": frame["ret_a"].corr(frame["ret_b"]),
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    with (results_dir / "stats.json").open("w") as handle:
        json.dump(stats, handle, indent=4)

    plt.figure(figsize=(12, 6))
    plt.plot(frame["date"], frame["norm_a"], label=symbol_a)
    plt.plot(frame["date"], frame["norm_b"], label=symbol_b)
    plt.xlabel("Date")
    plt.ylabel("Normalized Price")
    plt.legend()
    plt.tight_layout()
    plt.savefig(results_dir / "normalizedprices.png")
    plt.close()


if __name__ == "__main__":
    analyze()
