"""Read-only Alpaca adapter contract tests; no network or credentials needed."""
import io
import json
import unittest
from datetime import datetime, timezone
from Moneybot_V3.alpaca_market_data import fetch_verified_alpaca_trade


class Response:
    def __init__(self, value):
        self.data = io.BytesIO(json.dumps(value).encode())
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.data.close()
    def read(self, size):
        return self.data.read(size)


class AlpacaAdapterTests(unittest.TestCase):
    now = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)

    def fetch(self, payload, **kwargs):
        return fetch_verified_alpaca_trade(
            "AAPL", api_key="test-key", api_secret="test-secret", now=self.now,
            opener=lambda request, timeout: self.check_request(request, payload), **kwargs)

    def check_request(self, request, payload):
        self.assertEqual(request.full_url, "https://data.alpaca.markets/v2/stocks/AAPL/trades/latest")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Apca-api-key-id"), "test-key")
        return Response(payload)

    def test_valid_trade(self):
        result = self.fetch({"trade": {"p": 189.12, "t": "2026-11-17T14:59:30Z"}})
        self.assertEqual(result["price"], "189.12")
        self.assertEqual(result["provider"], "alpaca")

    def test_stale_and_future_rejected(self):
        for timestamp in ("2026-11-17T14:58:00Z", "2026-11-17T15:00:01Z"):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                self.fetch({"trade": {"p": 189, "t": timestamp}})

    def test_bad_payloads_rejected(self):
        for payload in ({}, {"trade": {}}, {"trade": {"p": -1, "t": "2026-11-17T15:00:00Z"}},
                        {"trade": {"p": True, "t": "2026-11-17T15:00:00Z"}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.fetch(payload)

    def test_credentials_required(self):
        with self.assertRaises(ValueError):
            fetch_verified_alpaca_trade("AAPL", api_key="", api_secret="")

    def test_invalid_symbol_rejected_before_network(self):
        with self.assertRaises(ValueError):
            fetch_verified_alpaca_trade("../orders", api_key="x", api_secret="y")


if __name__ == "__main__":
    unittest.main()
