"""Read-only V3 offline ledger dashboard contract tests."""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_ledger import PaperLedger
from paper_status_server import StatusHandler


@contextmanager
def running_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def get_json(url):
    try:
        with urlopen(url, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


class OfflineLedgerDashboardTest(unittest.TestCase):
    def test_unconfigured_fails_closed(self):
        old = os.environ.pop("MONEYBOT_V3_OFFLINE_LEDGER_PATH", None)
        try:
            with running_server() as url:
                status, body = get_json(url + "/paper-ledger-summary")
                self.assertEqual(status, 503)
                self.assertFalse(body["available"])
        finally:
            if old is not None:
                os.environ["MONEYBOT_V3_OFFLINE_LEDGER_PATH"] = old

    def test_readonly_inspection_does_not_create_lock_or_allow_fills(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "paper.sqlite")
            PaperLedger(path, starting_cash="1200.00")
            lock = Path(path + ".init.lock")
            lock.unlink()
            readonly = PaperLedger.open_readonly(path)
            self.assertEqual(readonly.audit_history()["audited_fills"], 0)
            self.assertEqual(readonly.snapshot()["cash"], "1200.00")
            self.assertFalse(lock.exists())
            with self.assertRaises(sqlite3.OperationalError):
                readonly.record_fill(
                    event_id="must-not-write", timestamp=datetime.now(timezone.utc),
                    symbol="TEST", side="BUY", quantity=1, price="1.00"
                )
            self.assertEqual(PaperLedger.open_readonly(path).snapshot()["fill_count"], 0)
            self.assertFalse(lock.exists())

    def test_existing_ledger_audited_but_never_trading_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "paper.sqlite")
            PaperLedger(path, starting_cash="1200.00")
            old = os.environ.get("MONEYBOT_V3_OFFLINE_LEDGER_PATH")
            os.environ["MONEYBOT_V3_OFFLINE_LEDGER_PATH"] = path
            try:
                with running_server() as url:
                    status, body = get_json(url + "/paper-ledger-summary")
                    self.assertEqual(status, 200)
                    self.assertEqual(body["cash"], "1200.00")
                    self.assertEqual(body["fill_count"], 0)
                    self.assertEqual(body["position_count"], 0)
                    self.assertFalse(body["trading_ready"])
                    self.assertIsNone(body["performance"])
                    self.assertEqual(get_json(url + "/readyz")[0], 503)
            finally:
                if old is None:
                    os.environ.pop("MONEYBOT_V3_OFFLINE_LEDGER_PATH", None)
                else:
                    os.environ["MONEYBOT_V3_OFFLINE_LEDGER_PATH"] = old


if __name__ == "__main__":
    unittest.main()
