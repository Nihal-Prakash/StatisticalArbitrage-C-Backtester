import json
import os
import numpy as np
import pandas as pd
from pathlib import Path

raw = json.loads((Path(__file__).parents[1] / "tickers.json").read_text())
existing = {f.name[:-4] for f in os.scandir(Path(__file__).parents[2] / "datasets/raw") if f.name.endswith(".csv")}
symbols = [s for s in dict.fromkeys(raw) if isinstance(s, str) and s in existing]

prices = pd.DataFrame({
    s: pd.read_csv(
        Path(__file__).parents[2] / f"datasets/raw/{s}.csv",
        usecols=["date", "close"],
        parse_dates=["date"]
    ).set_index("date")["close"]
    for s in symbols
}).sort_index().ffill().bfill()

returns = np.log(prices / prices.shift(1)).dropna()
returns = returns.loc[:, returns.std(axis=0) > 0]
symbols = list(returns.columns)

cov_matrix = np.cov(returns.values, rowvar=False)
corr_matrix = np.corrcoef(returns.values, rowvar=False)

r, c = np.triu_indices(len(symbols), k=1)
pair_covs = cov_matrix[r, c]
pair_corrs = corr_matrix[r, c]
order = np.argsort(-pair_corrs)

os.makedirs(Path(__file__).parents[2] / "results/exploration", exist_ok=True)
pd.DataFrame({
    "asset_a": [symbols[i] for i in r[order]],
    "asset_b": [symbols[j] for j in c[order]],
    "covariance": pair_covs[order],
    "correlation": pair_corrs[order]
}).to_csv(Path(__file__).parents[2] / "results/exploration/pairs_correlation.csv", index_label="rank")
