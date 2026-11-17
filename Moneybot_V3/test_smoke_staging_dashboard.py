"""Network-free regression tests for the V3 staging smoke-test redirect boundary."""
import unittest
from urllib.request import Request
from Moneybot_V3.smoke_staging_dashboard import RejectRedirects, check


class SmokeRedirectTests(unittest.TestCase):
    def test_cross_origin_redirect_is_rejected(self):
        handler = RejectRedirects()
        request = Request("https://moneybot-v3-staging.onrender.com/status")
        self.assertIsNone(handler.redirect_request(
            request, None, 302, "Found",
            {"Location": "https://example.com/collect"},
            "https://example.com/collect",
        ))

    def test_same_origin_redirect_is_also_rejected(self):
        handler = RejectRedirects()
        request = Request("https://moneybot-v3-staging.onrender.com/status")
        self.assertIsNone(handler.redirect_request(
            request, None, 301, "Moved",
            {"Location": "/"},
            "https://moneybot-v3-staging.onrender.com/",
        ))

    def test_rejects_noncanonical_origins_before_network(self):
        for url in (
            "http://moneybot-v3-staging.onrender.com",
            "https://moneybot-v3-staging.onrender.com.evil.example",
            "https://moneybot-v3-staging.onrender.com:443",
            "https://user@moneybot-v3-staging.onrender.com",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                check(url)


if __name__ == "__main__":
    unittest.main()
