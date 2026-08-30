import yfinance as yf
import pandas as pd
import os
import json
from pathlib import Path
from clean_data import clean
from validate_data import validate

symbols = json.loads((Path(__file__).parents[1] / "tickers.json").read_text())
if not isinstance(symbols, list) or not all(isinstance(symbol, str) and symbol for symbol in symbols):
    raise ValueError("tickers.json must contain a JSON array of non-empty ticker strings")

def download_symbol(symbol: str, period: str = "30d", interval: str = "1d"):
  return yf.download(
        symbol,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False
  )

def main():
    os.makedirs("datasets/raw", exist_ok=True)
    for symbol in symbols:
        raw = download_symbol(symbol)
        df = clean(raw)
        validate(df)

        df.to_csv(
            f"datasets/raw/{symbol}.csv",
            index=False
        )


if __name__ == "__main__":
    main()
