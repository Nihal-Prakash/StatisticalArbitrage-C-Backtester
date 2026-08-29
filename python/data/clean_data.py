import pandas as pd

def clean(df:pd.DataFrame) ->pd.DataFrame:
  df = df.reset_index()

  df.columns=[
    str(col[0]).lower()
    if isinstance(col,tuple)
    else str(col).lower()
    for col in df.columns
  ]

  required=["date",
          "open",
          "high",
          "low",
          "close",
          "volume"
          ]
  df=df[required]

  df["date"]=pd.to_datetime(df["date"])

  df=df.sort_values("date")
  df=df.reset_index(drop=True)

  duplicates = df[df.duplicated(subset=["date"])]

  print("Duplicate rows:", len(duplicates))
  df = df.drop_duplicates(subset=["date"])

  print(df.isna().sum())
  df = df.dropna(
    subset=["open", "high", "low", "close"]
  )
  return df
