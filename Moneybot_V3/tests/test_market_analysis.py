"""No-network market analysis tests."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from market_analysis import analyze_window


class MarketAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
        self.samples = [
            {"provider": "alpaca", "symbol": "SPY", "authenticated": True,
             "execution_authorized": False,
             "timestamp_utc": (self.now - timedelta(seconds=80 - 15 * i)).isoformat(),
             "price": f"{100 + i:.2f}"}
            for i in range(5)
        ]

    def analyze(self, samples=None):
        return analyze_window(self.samples if samples is None else samples,
                              symbol="SPY", now=self.now)

    def test_buy_signal_never_authorizes_execution(self):
        result = self.analyze()
        self.assertEqual(result["signal"], "BUY")
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["profitability_unverified"])

    def test_sell_and_hold(self):
        sell = [{**x, "price": f"{104 - i:.2f}"} for i, x in enumerate(self.samples)]
        self.assertEqual(self.analyze(sell)["signal"], "SELL")
        hold = [{**x, "price": "100.00"} for x in self.samples]
        self.assertEqual(self.analyze(hold)["signal"], "HOLD")

    def test_rejects_unauthenticated_duplicate_and_stale(self):
        bad = [
            [{**self.samples[0], "authenticated": False}, *self.samples[1:]],
            [self.samples[0], self.samples[0], *self.samples[2:]],
            [{**x, "timestamp_utc": (self.now - timedelta(hours=1, seconds=80 - 15 * i)).isoformat()}
             for i, x in enumerate(self.samples)],
            [{**self.samples[0], "symbol": "QQQ"}, *self.samples[1:]],
            [{**self.samples[0], "price": "NaN"}, *self.samples[1:]],
        ]
        for samples in bad:
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                self.analyze(samples)


if __name__ == "__main__":
    unittest.main()
