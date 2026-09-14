from __future__ import annotations
from abc import ABC , abstractmethod
from enum import Enum
import pandas as pd

class Signal(str,Enum):
    BUY="BUY"
    SELL="SELL"
    HOLD="HOLD"

class Strategy(ABC):
    @abstractmethod
    def on_bar(self,bar: pd.Series) -> Signal: ...

    @abstractmethod
    def reset(self) -> None: ...
