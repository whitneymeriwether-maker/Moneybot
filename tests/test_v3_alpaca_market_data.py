"""Alpaca read-only quote adapter contract tests, no external network."""
import io
import json
import unittest
from datetime import datetime, timezone
from Moneybot_V3.alpaca_market_data import latest_alpaca_quote


class Response:
    status = 200
    def __init__(self, payload):
        self.stream = io.BytesIO(json.dumps(payload).encode())
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.stream.close()
    def read(self, n):
        return self.stream.read(n)


class AlpacaAdapterTests(unittest.TestCase):
    now = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)

    def fetch(self, payload):
        def opener(request, timeout):
            self.assertEqual(request.full_url, "https://data.alpaca.markets/v2/stocks/AAPL/quotes/latest?feed=iex")
            self.assertEqual(request.get_header("Apca-api-key-id"), "test-key")
            return Response(payload)
        return latest_alpaca_quote("AAPL", key_id="test-key", secret_key="test-secret",
                                   now=self.now, opener=opener)

    def test_valid_quote_is_not_execution(self):
        result = self.fetch({"symbol": "AAPL", "quote": {
            "bp": 189.10, "ap": 189.12, "t": "2026-11-17T14:59:30Z"}})
        self.assertEqual(result["feed"], "iex")
        self.assertEqual(result["execution_authorized"], False)

    def test_stale_future_and_crossed_quotes_fail_closed(self):
        for bid, ask, timestamp in (
            (189.10, 189.12, "2026-11-17T14:50:00Z"),
            (189.10, 189.12, "2026-11-17T15:00:01Z"),
            (190.00, 189.00, "2026-11-17T14:59:30Z"),
        ):
            with self.subTest(timestamp=timestamp, bid=bid), self.assertRaises(ValueError):
                self.fetch({"symbol": "AAPL", "quote": {"bp": bid, "ap": ask, "t": timestamp}})

    def test_symbol_mismatch_and_missing_credentials(self):
        with self.assertRaises(ValueError):
            self.fetch({"symbol": "MSFT", "quote": {
                "bp": 189.10, "ap": 189.12, "t": "2026-11-17T14:59:30Z"}})
        with self.assertRaises(ValueError):
            latest_alpaca_quote("AAPL", key_id="", secret_key="")


if __name__ == "__main__":
    unittest.main()
