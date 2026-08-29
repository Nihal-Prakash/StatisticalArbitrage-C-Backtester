import yfinance as yf
import pandas as pd
import os
from clean_data import clean
from validate_data import validate

symbols =( 
        "RELIANCE.NS",
        "TCS.NS" 
)
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
