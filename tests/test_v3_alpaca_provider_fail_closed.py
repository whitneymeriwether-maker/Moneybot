"""Fail-closed regression cases for the authenticated read-only Alpaca IEX adapter.

No credentials, network, orders, or external services are used.
"""
import io
import unittest
from datetime import datetime, timezone
from Moneybot_V3.alpaca_market_data import latest_alpaca_quote


class Response:
    status = 200

    def __init__(self, body):
        self.body = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.body.close()

    def read(self, count):
        return self.body.read(count)


class MalformedProviderResponseTests(unittest.TestCase):
    NOW = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)
    GOOD = b'{"symbol":"AAPL","quote":{"bp":189.10,"ap":189.12,"t":"2026-11-17T14:59:30Z"}}'

    def fetch(self, raw, status=200):
        def transport(request, timeout):
            self.assertEqual(request.get_method(), "GET")
            self.assertTrue(request.full_url.startswith("https://data.alpaca.markets/"))
            response = Response(raw)
            response.status = status
            return response
        return latest_alpaca_quote(
            "AAPL", key_id="test-key", secret_key="test-secret",
            now=self.NOW, opener=transport)

    def test_valid_quote_is_observation_only(self):
        result = self.fetch(self.GOOD)
        self.assertIs(result["execution_authorized"], False)
        self.assertEqual(result["feed"], "iex")

    def test_reject_duplicate_fields_at_any_depth(self):
        bodies = (
            b'{"symbol":"AAPL","symbol":"AAPL","quote":{"bp":189.10,"ap":189.12,"t":"2026-11-17T14:59:30Z"}}',
            b'{"symbol":"AAPL","quote":{"bp":189.10,"bp":189.10,"ap":189.12,"t":"2026-11-17T14:59:30Z"}}',
        )
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.fetch(body)

    def test_reject_oversized_or_non_success_response(self):
        with self.assertRaises(ValueError):
            self.fetch(b" " * 65537)
        with self.assertRaises(ValueError):
            self.fetch(self.GOOD, status=401)

    def test_reject_ambiguous_or_unrepresentable_prices(self):
        for price in (b'true', b'1e2', b'-1', b'189.101', b'99999999', b'null'):
            body = self.GOOD.replace(b'189.10', price)
            with self.subTest(price=price), self.assertRaises(ValueError):
                self.fetch(body)

    def test_reject_subcent_midpoint(self):
        body = self.GOOD.replace(b'189.12', b'189.11')
        with self.assertRaises(ValueError):
            self.fetch(body)


if __name__ == "__main__":
    unittest.main()
