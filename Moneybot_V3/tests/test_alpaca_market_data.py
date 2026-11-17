"""Network-free Alpaca data adapter contract tests."""
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alpaca_market_data import latest_alpaca_quote


class Response:
    status = 200
    def __init__(self, payload):
        self.payload = io.BytesIO(json.dumps(payload).encode())
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, n):
        return self.payload.read(n)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
        self.payload = {"symbol": "SPY", "quote": {
            "t": "2026-11-14T15:59:40.123456789Z", "bp": 500.20, "ap": 500.30}}
    def fetch(self):
        def opener(request, timeout):
            self.assertEqual(request.full_url,
                             "https://data.alpaca.markets/v2/stocks/SPY/quotes/latest?feed=iex")
            self.assertEqual(request.get_header("Apca-api-key-id"), "test")
            return Response(self.payload)
        return latest_alpaca_quote("SPY", key_id="test", secret_key="secret",
                                   now=self.now, opener=opener)
    def test_valid_quote_is_not_a_fill(self):
        value = self.fetch()
        self.assertEqual(value["price"], "500.25")
        self.assertEqual(value["feed"], "iex")
        self.assertFalse(value["execution_authorized"])
    def test_provider_numeric_inputs_fail_closed(self):
        for bad in ("9" * 1000, "1e3", "-1.00", "500.001", "NaN", "10000000.00"):
            with self.subTest(bad=bad[:30]):
                self.payload["quote"]["bp"] = bad
                with self.assertRaises(ValueError):
                    self.fetch()
                self.payload["quote"]["bp"] = 500.20

    def test_missing_credentials_fail_before_network(self):
        with self.assertRaises(ValueError):
            latest_alpaca_quote("SPY", key_id="", secret_key="", opener=lambda *a, **k: self.fail("network"))
    def test_stale_crossed_missing_and_mismatched_rejected(self):
        for change in ({"symbol": "QQQ"},
                       {"quote": {"t": "2026-11-14T15:00:00Z", "bp": 500.2, "ap": 500.3}},
                       {"quote": {"t": "2026-11-14T15:59:40Z", "bp": 501, "ap": 500}},
                       {"quote": {"t": "2026-11-14T15:59:40Z", "bp": 500.20}}):
            with self.subTest(change=change):
                original = self.payload
                self.payload = {**original, **change}
                with self.assertRaises(ValueError):
                    self.fetch()
                self.payload = original


if __name__ == "__main__":
    unittest.main()
