from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def correlate(input_path: Path, output_path: Path) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"{input_path} not found")
    prices = pd.read_csv(input_path, index_col="date", parse_dates=["date"])
    returns = np.log(prices / prices.shift(1)).dropna()
    returns = returns.loc[:, returns.std(axis=0) > 0]
    symbols = list(returns.columns)

    cov_matrix = np.cov(returns.values, rowvar=False)
    corr_matrix = np.corrcoef(returns.values, rowvar=False)

    r, c = np.triu_indices(len(symbols), k=1)
    pair_covs = cov_matrix[r, c]
    pair_corrs = corr_matrix[r, c]
    order = np.argsort(-pair_corrs)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "asset_a": [symbols[i] for i in r[order]],
        "asset_b": [symbols[j] for j in c[order]],
        "covariance": pair_covs[order],
        "correlation": pair_corrs[order]
    }).to_csv(output_path, index_label="rank")


def analyze(input_path: Path = ROOT / "datasets/intraday.csv",
            output_path: Path = ROOT / "results/intraday_correlation.csv") -> None:
    correlate(input_path, output_path)


if __name__ == "__main__":
    analyze()
