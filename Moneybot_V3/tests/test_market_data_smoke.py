"""Market-data smoke command contract tests, offline and credential-free."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from market_data_smoke import probe, main


class MarketDataSmokeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 14, 20, 0, tzinfo=timezone.utc)
        self.quote = {
            "authenticated": True, "execution_authorized": False,
            "symbol": "SPY", "provider": "alpaca", "feed": "iex",
            "price_type": "bid_ask_midpoint_not_execution",
            "timestamp_utc": self.now.isoformat(), "price": "500.00",
        }

    def test_authenticated_readonly_probe(self):
        result = probe("SPY", now=self.now, fetcher=lambda symbol, now: self.quote)
        self.assertTrue(result["ok"])
        self.assertFalse(result["paper_trading_enabled"])
        self.assertFalse(result["executable_fill"])
        self.assertFalse(result["broker_orders_enabled"])

    def test_rejects_unauthenticated_and_executable_claims(self):
        for field, value in (("authenticated", False), ("execution_authorized", True),
                             ("symbol", "QQQ"), ("feed", "unknown"),
                             ("price_type", "last_trade")):
            with self.subTest(field=field):
                changed = dict(self.quote, **{field: value})
                with self.assertRaises(ValueError):
                    probe("SPY", now=self.now, fetcher=lambda symbol, now: changed)

    def test_invalid_symbol_rejected_before_network(self):
        with self.assertRaises(ValueError):
            probe("../orders", now=self.now, fetcher=lambda symbol, now: self.fail("network"))

    def test_command_rejects_missing_symbol(self):
        self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
