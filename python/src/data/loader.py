from pathlib import Path
import pandas as pd

REQUIRED = ["open", "high", "low", "close", "volume"]

def load(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()

    if df.index.duplicated().sum():
        raise ValueError(f"{df.index.duplicated().sum()} duplicate timestamps.")

    if df[REQUIRED].isna().any().any():
        raise ValueError(f"NaN values:\n{df[REQUIRED].isna().sum()}")

    assert (df[["open","high","low","close"]] > 0).all().all()
    assert (df["volume"] >= 0).all()
    assert (df["high"] >= df[["open","close","low"]].max(axis=1)).all()
    assert (df["low"]  <= df[["open","close"]].min(axis=1)).all()

    return df[REQUIRED]
