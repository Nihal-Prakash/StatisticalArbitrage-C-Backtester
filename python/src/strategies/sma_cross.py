from __future__ import annotations
from collections import deque
from enum import Enum
import pandas as pd
from .base import Signal , Strategy

class _Pos(str,Enum):
    FLAT ="FLAT"
    LONG ="LONG"

class SMACross(Strategy):
    def __init__(self,fast_window : int=20 , slow_window: int=50) -> None:
        if fast_window >=slow_window:
            raise ValueError(" Window value err")
        self.fast_window=fast_window
        self.slow_window=slow_window
        self.reset()

    def on_bar(self,bar: pd.Series) -> Signal:
        self._prices.append(float(bar["close"]))
        self._n += 1

        if self._n <self.slow_window:
            return Signal.HOLD

        fast = sum(list(self._prices)[-self.fast_window:]) /self.fast_window
        slow = sum(self._prices) /self.slow_window

        sig=Signal.HOLD
        if self._pf is not None:
            if self._pf <=self._ps and fast > slow and self._pos is _Pos.FLAT:
                sig,self._pos = Signal.BUY , _Pos.LONG
            elif self._pf>=self._ps and fast < slow and self._pos is _Pos.LONG:
                sig,self._pos = Signal.SELL , _Pos.FLAT

        self._pf , self._ps=fast,slow
        return sig
    def reset(self) -> None:
        self._prices: deque = deque(maxlen=self.slow_window)
        self._n = 0
        self._pf = None
        self._ps = None
        self._pos = _Pos.FLAT
