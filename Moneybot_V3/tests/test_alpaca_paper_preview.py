"""Network-free end-to-end data-to-audited-account preview tests.

The fake transport is synthetic and proves no real provider connectivity.
"""
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from Moneybot_V3.alpaca_paper_preview import preview_alpaca_paper_buy
from Moneybot_V3.paper_ledger import PaperLedger
from Moneybot_V3.paper_risk_preflight import PaperRiskRejected


class Response:
    status = 200
    def __init__(self, payload):
        self.stream = io.BytesIO(json.dumps(payload).encode())
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size):
        return self.stream.read(size)


class AlpacaPaperPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = PaperLedger(Path(self.tmp.name) / "paper.sqlite", starting_cash="1000.00")
        self.now = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
        self.payload = {"symbol": "SPY", "quote": {
            "t": "2026-11-14T15:59:40Z", "bp": 100.20, "ap": 100.30}}
        self.calls = 0

    def opener(self, request, timeout):
        self.calls += 1
        self.assertEqual(request.full_url,
                         "https://data.alpaca.markets/v2/stocks/SPY/quotes/latest?feed=iex")
        self.assertEqual(request.get_header("Apca-api-key-id"), "synthetic-key")
        return Response(self.payload)

    def preview(self, **overrides):
        args = dict(ledger=self.ledger, symbol="SPY", quantity="2",
                    max_order_notional="500.00", max_position_notional="600.00",
                    paper_only=True, kill_switch=False, now=self.now,
                    key_id="synthetic-key", secret_key="synthetic-secret",
                    opener=self.opener)
        args.update(overrides)
        return preview_alpaca_paper_buy(**args)

    def test_authenticated_quote_and_audited_account_are_read_only(self):
        before = self.ledger.snapshot()
        result = self.preview()
        self.assertEqual(result["status"], "preflight_only_not_executed")
        self.assertEqual(result["reference_price"], "100.25")
        self.assertEqual(result["reference_notional"], "200.50")
        self.assertEqual(result["account_source"], "audited_local_hypothetical_ledger")
        self.assertEqual(result["feed"], "iex")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["ledger_mutated"])
        self.assertEqual(self.ledger.snapshot(), before)
        self.assertEqual(self.calls, 1)

    def test_missing_credentials_and_kill_switch_fail_closed(self):
        for change in ({"key_id": ""}, {"paper_only": False},
                       {"kill_switch": True}):
            with self.subTest(change=change):
                before = self.ledger.snapshot()
                with self.assertRaises(PaperRiskRejected):
                    self.preview(**change)
                self.assertEqual(self.ledger.snapshot(), before)
        self.assertEqual(self.calls, 0)

    def test_bad_quote_and_risk_fail_without_fill(self):
        for change in (
            {"symbol": "QQQ"},
            {"symbol": "SPY", "quote": {"t": "2026-11-14T15:00:00Z", "bp": 100.20, "ap": 100.30}},
            {"symbol": "SPY", "quote": {"t": "2026-11-14T15:59:40Z", "bp": 101, "ap": 100}},
        ):
            with self.subTest(change=change):
                self.payload = change
                with self.assertRaises(PaperRiskRejected):
                    self.preview()
                self.assertEqual(self.ledger.snapshot()["fill_count"], 0)
        self.payload = {"symbol": "SPY", "quote": {
            "t": "2026-11-14T15:59:40Z", "bp": 100.20, "ap": 100.30}}
        for overrides in ({"quantity": "20"}, {"max_order_notional": "100.00"},
                          {"max_position_notional": "100.00"}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(PaperRiskRejected):
                    self.preview(**overrides)
                self.assertEqual(self.ledger.snapshot()["fill_count"], 0)

    def test_ledger_audit_failure_blocks_preview(self):
        with patch.object(self.ledger, "audit_history", side_effect=ValueError("corrupt")):
            with self.assertRaises(PaperRiskRejected):
                self.preview()
        self.assertEqual(self.ledger.snapshot()["fill_count"], 0)


if __name__ == "__main__":
    unittest.main()
