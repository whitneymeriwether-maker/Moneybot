"""Restart and rejection tests; no external data or orders."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from Moneybot_V3.observation_window import ObservationWindow


class ObservationWindowTests(unittest.TestCase):
    def test_restart_and_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "observations.sqlite"
            now = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
            window = ObservationWindow(path)
            for i in range(5):
                stamp = (now - timedelta(seconds=80 - 20*i)).isoformat(timespec="microseconds")
                window.append({"authenticated": True, "execution_authorized": False,
                               "provider": "alpaca", "symbol": "SPY",
                               "timestamp_utc": stamp, "price": f"{500+i}.00"})
            restored = ObservationWindow(path)
            result = restored.analyze("SPY", now)
            self.assertEqual(result["signal"], "BUY")
            self.assertFalse(result["execution_authorized"])
            self.assertTrue(result["candidate_only"])
            with self.assertRaises(ValueError):
                restored.append({"authenticated": True, "execution_authorized": False,
                                 "provider": "alpaca", "symbol": "SPY",
                                 "timestamp_utc": stamp, "price": "504.00"})

    def test_unverified_observation_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            window = ObservationWindow(Path(temp) / "window.sqlite")
            with self.assertRaises(ValueError):
                window.append({"authenticated": False, "execution_authorized": False,
                               "provider": "alpaca", "symbol": "SPY",
                               "timestamp_utc": "2026-11-14T15:00:00.000000+00:00",
                               "price": "500.00"})


if __name__ == "__main__":
    unittest.main()
