from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import pandas as pd

DATA_DIR = Path("data")
ET = ZoneInfo("America/New_York")

@dataclass
class RiskConfig:
    risk_per_trade: float = 0.005
    daily_loss_limit: float = 0.015
    max_exposure: float = 0.25

class PaperLedger:
    """CSV journal only. This class intentionally does not send broker orders."""
    def __init__(self, data_dir=DATA_DIR):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.signals_path = self.data_dir / "signals.csv"
        self.trades_path = self.data_dir / "trades.csv"

    def record_signal(self, symbol, signal, features):
        record = {
            "timestamp_et": datetime.now(ET).isoformat(),
            "symbol": symbol,
            **signal,
            "feature_snapshot": json.dumps({k: str(v) for k, v in features.items()}, default=str),
        }
        self._append(self.signals_path, record)

    def record_trade(self, record):
        self._append(self.trades_path, record)

    @staticmethod
    def _append(path, record):
        df = pd.DataFrame([record])
        df.to_csv(path, mode="a", header=not path.exists(), index=False)

    @staticmethod
    def _read(path):
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path)

    def read_signals(self):
        return self._read(self.signals_path)

    def read_trades(self):
        return self._read(self.trades_path)
