from __future__ import annotations
import math
import pandas as pd

def total_return(equity: pd.Series) -> float:
    if len(equity) < 2:
        raise ValueError ("Need at least 2 points")
    return float(equity.iloc[-1] / equity.iloc[0] -1)

def daily_returns(equity: pd.Series) -> pd.Series:
    return equity.resample("1D").last().dropna().pct_change().iloc[1:]

def max_drawdown(equity: pd.Series) -> float:
    return float ((equity/equity.cummax() -1).min())

def sharpe_ratio(equity:pd.Series , risk_free : float =0.0) -> float:
    r=daily_returns(equity) - risk_free
    sigma=r.std(ddof=1)
    if sigma == 0 or math.isnan(sigma):
        return float("nan")
    else:
        return float(math.sqrt(252)* r.mean() /sigma)
