"""Real HTTP smoke contract for the isolated, read-only V3 staging dashboard."""
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_status_server import StatusHandler


class StagingHTTPContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), StatusHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path, method="GET"):
        request = Request(self.base + path, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read(), response.headers
        except HTTPError as error:
            return error.code, error.read(), error.headers

    def test_browser_dashboard_is_actual_only_and_not_activated(self):
        status, body, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        for required in (
            b"System health", b"Account state", b"Paper trades",
            b"Risk limits", b"Performance", b"NOT ACTIVATED",
            b"no demo balances", b"hypothetical",
        ):
            self.assertIn(required.lower(), body.lower())

    def test_health_is_not_trading_readiness(self):
        status, body, _ = self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["trading_state"], "NOT_ACTIVATED")
        status, body, _ = self.request("/readyz")
        self.assertEqual(status, 503)
        self.assertIs(json.loads(body)["ready_for_automatic_paper_trading"], False)
        status, body, _ = self.request("/readyz", method="HEAD")
        self.assertEqual(status, 503)
        self.assertEqual(body, b"")

    def test_missing_accounting_never_becomes_demo_data(self):
        with patch.dict(os.environ, {
            "MONEYBOT_V3_PAPER_JOURNAL_PATH": "",
            "MONEYBOT_V3_OFFLINE_LEDGER_PATH": "",
        }):
            for endpoint in (
                "/paper-account", "/paper-journal-activity",
                "/paper-ledger-summary", "/paper-ledger-fills",
            ):
                with self.subTest(endpoint=endpoint):
                    status, body, _ = self.request(endpoint)
                    self.assertEqual(status, 503)
                    self.assertIs(json.loads(body)["available"], False)

    def test_no_http_order_or_mutation_path(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                status, body, _ = self.request("/orders", method=method)
                self.assertEqual(status, 405)
                self.assertEqual(json.loads(body)["error"], "read-only service")
        status, body, _ = self.request("/status")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertIs(state["automatic_paper_trading"], False)
        self.assertIs(state["real_money_trading"], False)


if __name__ == "__main__":
    unittest.main()
