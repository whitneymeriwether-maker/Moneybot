"""Regression checks for redirect-safe V3 staging smoke tests."""
import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from Moneybot_V3.smoke_staging import NoRedirect, fetch


class RedirectSafetyTests(unittest.TestCase):
    def test_redirect_handler_rejects_cross_origin_redirect(self):
        handler = NoRedirect()
        request = Request("https://staging.example/healthz")
        self.assertIsNone(handler.redirect_request(
            request, None, 302, "Found",
            {"Location": "http://untrusted.example/"}, "http://untrusted.example/"))

    def test_redirect_response_is_not_success(self):
        error = HTTPError("https://staging.example/healthz", 302, "Found",
                          {"Location": "http://untrusted.example/"}, io.BytesIO(b""))
        with patch("Moneybot_V3.smoke_staging._OPENER.open", side_effect=error):
            status, _, body = fetch("https://staging.example", "/healthz")
        self.assertEqual(status, 302)
        self.assertEqual(body, b"")


if __name__ == "__main__":
    unittest.main()
