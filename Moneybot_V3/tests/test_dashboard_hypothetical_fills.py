"""HTTP regression: audited local hypothetical fills must never imply executions."""
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from paper_ledger import PaperLedger
from paper_status_server import StatusHandler


class HypotheticalFillDashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "isolated.sqlite")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), StatusHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def fetch(self):
        with urlopen(self.base + "/paper-ledger-fills") as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def test_unconfigured_fails_closed(self):
        with patch.dict(os.environ, {"MONEYBOT_V3_OFFLINE_LEDGER_PATH": ""}):
            with self.assertRaises(HTTPError) as failure:
                self.fetch()
            self.assertEqual(failure.exception.code, 503)

    def test_audited_fills_are_explicitly_hypothetical(self):
        ledger = PaperLedger(self.path, starting_cash="1000.00")
        ledger.record_fill(event_id="test-buy", timestamp=datetime.now(timezone.utc),
                           symbol="SPY", side="BUY", quantity=2, price="101.25")
        with patch.dict(os.environ, {"MONEYBOT_V3_OFFLINE_LEDGER_PATH": self.path}):
            result = self.fetch()
            self.assertEqual(result["source"], "local_hypothetical_sqlite_ledger")
            self.assertEqual(result["verification"], "audited_local_records_not_broker_verified")
            self.assertIs(result["trading_ready"], False)
            self.assertEqual(result["fill_count"], 1)
            self.assertEqual(result["fills"][0]["price"], "101.25")
            self.assertEqual(result["fills"][0]["side"], "BUY")

    def test_corrupt_history_fails_closed(self):
        ledger = PaperLedger(self.path, starting_cash="1000.00")
        ledger.record_fill(event_id="test-buy", timestamp=datetime.now(timezone.utc),
                           symbol="SPY", side="BUY", quantity=1, price="10.00")
        import sqlite3
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE paper_fills SET price_cents=100 WHERE event_id='test-buy'")
        with patch.dict(os.environ, {"MONEYBOT_V3_OFFLINE_LEDGER_PATH": self.path}):
            with self.assertRaises(HTTPError) as failure:
                self.fetch()
            self.assertEqual(failure.exception.code, 503)


if __name__ == "__main__":
    unittest.main()
