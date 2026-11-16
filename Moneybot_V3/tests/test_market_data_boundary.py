import unittest
from datetime import datetime, timezone, timedelta
from market_data_boundary import verified_quote, UnverifiedMarketData

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)

def sample():
    return {"symbol": "AAPL", "price": "120.50", "timestamp_utc": "2026-11-16T11:59:30Z",
            "provider": "test-adapter", "authenticated_transport": True, "provider_verified": True}

class QuoteBoundaryTests(unittest.TestCase):
    def test_verified(self):
        self.assertEqual(str(verified_quote(sample(), expected_symbol="AAPL", now=NOW)["price"]), "120.50")

    def test_reject_unsafe(self):
        mutations = [
            {"symbol": "MSFT"}, {"price": 120.5}, {"price": "NaN"}, {"price": "-1"},
            {"price": "0"}, {"price": "1e3"}, {"price": "99999999"},
            {"timestamp_utc": "2026-11-16T11:50:00Z"},
            {"timestamp_utc": "2026-11-16T12:00:01Z"},
            {"timestamp_utc": "2026-11-16T11:59:30"},
            {"provider": ""}, {"provider_verified": False}, {"authenticated_transport": False},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(UnverifiedMarketData):
                verified_quote({**sample(), **mutation}, expected_symbol="AAPL", now=NOW)

    def test_malformed_symbol_and_clock_fail_closed(self):
        for symbol in (None, 123, [], {}, True):
            with self.subTest(symbol=symbol), self.assertRaises(UnverifiedMarketData):
                verified_quote(sample(), expected_symbol=symbol, now=NOW)
        for clock in ("2026-11-16T12:00:00Z", 0, [], {}, False):
            with self.subTest(clock=clock), self.assertRaises(UnverifiedMarketData):
                verified_quote(sample(), expected_symbol="AAPL", now=clock)

    def test_missing_attestation(self):
        for key in ("authenticated_transport", "provider_verified", "timestamp_utc", "provider"):
            q = sample()
            del q[key]
            with self.subTest(key=key), self.assertRaises(UnverifiedMarketData):
                verified_quote(q, expected_symbol="AAPL", now=NOW)

    def test_reject_bad_clock_and_policy(self):
        with self.assertRaises(UnverifiedMarketData):
            verified_quote(sample(), expected_symbol="AAPL", now=NOW.replace(tzinfo=None))
        with self.assertRaises(UnverifiedMarketData):
            verified_quote(sample(), expected_symbol="AAPL", now=NOW, max_age_seconds=0)

if __name__ == "__main__":
    unittest.main()
