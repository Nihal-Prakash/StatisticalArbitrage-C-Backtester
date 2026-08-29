import pandas as pd 

def validate(df:pd.DataFrame) -> None :
    assert df["date"].is_monotonic_increasing
    assert not df["date"].duplicated().any()

    assert(df["open"]>0).all()
    assert(df["high"]>0).all()
    assert(df["low"]>0).all()
    assert(df["close"]>0).all()

    assert (df["high"] >= df["low"]).all()
    assert (df["volume"] >= 0).all()

    assert (df["high"] >= df["open"]).all()
    assert (df["high"] >= df["close"]).all()

    assert (df["low"] <= df["open"]).all()


