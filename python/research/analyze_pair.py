import pandas as pd 
import numpy as np 
import json
import os

symbol_a = "RELIANCE.NS"
symbol_b = "TCS.NS"

a = pd.read_csv(
    "datasets/raw/RELIANCE.NS.csv",
    parse_dates = ["date"]
)

b = pd.read_csv(
    "datasets/raw/TCS.NS.csv",
    parse_dates = ["date"]
)

df = pd.merge(
    a[["date", "close"]],
    b[["date", "close"]],

    on = "date",
    how = "inner",

    suffixes = ("_a", "_b")
)

df = df.sort_values("date")

df["ret_a"] = np.log(
    df["close_a"] / df["close_a"].shift(1)
)

df["ret_b"] = np.log(
    df["close_b"] / df["close_b"].shift(1)
)

df = df.dropna()

df["norm_a"] = (
    100 * df["close_a"] / df["close_a"].iloc[0]
)

df["norm_b"] = (
    100 * df["close_b"] / df["close_b"].iloc[0]
)

mean_a = df["ret_a"].mean()
mean_b = df["ret_b"].mean()

std_a = df["ret_a"].std()
std_b = df["ret_b"].std()

cov = df["ret_a"].cov(df["ret_b"])
corr = df["ret_a"].corr(df["ret_b"])

price_corr = df["close_a"].corr(df["close_b"])
return_corr = df["ret_a"].corr(df["ret_b"])

stats = {
    "asset_a": symbol_a,
    "asset_b": symbol_b,
    "observations": len(df),

    "mean_return_a": mean_a,
    "mean_return_b": mean_b,

    "std_return_a": std_a,
    "std_return_b": std_b,

    "covariance": cov,
    "return_correlation": corr,
}

os.makedirs("results/exploration", exist_ok=True)

with open(
    "results/exploration/statistics.json",
    "w"
) as f:
    json.dump(stats, f, indent=4)
