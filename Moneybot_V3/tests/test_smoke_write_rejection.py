"""Regression checks for write rejection in external V3 smoke probes."""
import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from Moneybot_V3.smoke_staging import fetch


class ReadOnlyProbeTests(unittest.TestCase):
    def test_post_is_sent_as_post_and_405_is_reported(self):
        observed = []
        def reject(req, timeout):
            observed.append((req.full_url, req.get_method(), timeout))
            raise HTTPError(req.full_url, 405, "Method Not Allowed",
                            {"Content-Type": "application/json"},
                            io.BytesIO(b'{"error":"read-only service"}'))
        with patch("Moneybot_V3.smoke_staging._OPENER.open", side_effect=reject):
            status, _, body = fetch("https://staging.example", "/orders", method="POST")
        self.assertEqual(observed, [("https://staging.example/orders", "POST", 12)])
        self.assertEqual(status, 405)
        self.assertEqual(body, b'{"error":"read-only service"}')


if __name__ == "__main__":
    unittest.main()
