import yfinance as yf
import pandas as pd
import os
import json
from pathlib import Path
from clean_data import clean
from validate_data import validate

symbols = list(dict.fromkeys(json.loads((Path(__file__).parents[1] / "tickers.json").read_text())))

def download_symbol(symbol: str, period: str = "1d", interval: str = "15m"):
    return yf.download(
        symbol,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False
    )

def main():
    os.makedirs(Path(__file__).parents[2] / "datasets/raw", exist_ok=True)
    for symbol in symbols:
        try:

            raw = download_symbol(symbol)
            if raw.empty:
                print(f"No data found for {symbol}")
                continue
            df = clean(raw)
            validate(df)

            df.to_csv(
                Path(__file__).parents[2] / f"datasets/raw/{symbol}.csv",
                index=False
            )
        except Exception as e:
            print (f"{e}")


if __name__ == "__main__":
    main()
