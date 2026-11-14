"""Offline contract tests: no network, credentials, broker or orders."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verified_market_quote import verified_quote


class QuoteBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
        self.quote = {"symbol": "SPY", "timestamp": self.now - timedelta(seconds=20), "price": "500.25"}

    def validate(self, **kwargs):
        return verified_quote(self.quote, provider="alpaca", authenticated=True,
                              expected_symbol="SPY", now=self.now, **kwargs)

    def test_valid_quote_is_not_execution_authorization(self):
        result = self.validate()
        self.assertEqual(result["price"], "500.25")
        self.assertFalse(result["execution_authorized"])

    def test_authentication_required(self):
        with self.assertRaises(ValueError):
            verified_quote(self.quote, provider="alpaca", authenticated=False,
                           expected_symbol="SPY", now=self.now)

    def test_stale_future_and_mismatched_symbols_rejected(self):
        for value in (self.now - timedelta(seconds=91), self.now + timedelta(seconds=1)):
            with self.subTest(value=value):
                self.quote["timestamp"] = value
                with self.assertRaises(ValueError):
                    self.validate()
        self.quote["timestamp"] = self.now
        self.quote["symbol"] = "QQQ"
        with self.assertRaises(ValueError):
            self.validate()

    def test_bad_prices_rejected(self):
        for price in ("NaN", "Infinity", "-1", "0", "1.001", 100.00, "1000001"):
            with self.subTest(price=price):
                self.quote["price"] = price
                with self.assertRaises(ValueError):
                    self.validate()

    def test_unknown_provider_and_missing_fields_rejected(self):
        with self.assertRaises(ValueError):
            verified_quote(self.quote, provider="unverified", authenticated=True,
                           expected_symbol="SPY", now=self.now)
        del self.quote["timestamp"]
        with self.assertRaises(ValueError):
            self.validate()


if __name__ == "__main__":
    unittest.main()
