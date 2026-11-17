"""Contract tests for the authenticated-quote boundary (no network required)."""
import unittest
from datetime import datetime, timezone, timedelta

from verified_quote import verify_quote


class VerifiedQuoteTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)
        self.quote = dict(provider="testfeed", symbol="SPY", price="500.1234",
                          observed_at="2026-11-17T15:59:30Z",
                          verified_transport=True)

    def test_valid_observation(self):
        self.assertEqual(verify_quote(self.quote, expected_symbol="SPY", now=self.now)["price"], "500.1234")

    def test_fail_closed_cases(self):
        cases = [
            {"verified_transport": False}, {"verified_transport": "true"},
            {"symbol": "QQQ"}, {"price": 500.12}, {"price": "0"},
            {"price": "NaN"}, {"price": "1e4"}, {"price": "1.12345"},
            {"provider": ""}, {"observed_at": "2026-11-17T15:58:00Z"},
            {"observed_at": "2026-11-17T16:00:01Z"},
            {"observed_at": "2026-11-17T15:59:30+00:00"},
        ]
        for change in cases:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    verify_quote({**self.quote, **change}, expected_symbol="SPY", now=self.now)

    def test_missing_transport_and_bad_policy(self):
        with self.assertRaises(ValueError):
            verify_quote({k: v for k, v in self.quote.items() if k != "verified_transport"},
                         expected_symbol="SPY", now=self.now)
        with self.assertRaises(ValueError):
            verify_quote(self.quote, expected_symbol="SPY", now=self.now, max_age_seconds=0)


if __name__ == "__main__":
    unittest.main()
