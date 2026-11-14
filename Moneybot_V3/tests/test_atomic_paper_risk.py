"""Atomic paper ledger risk regression tests (no broker or network)."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_ledger import PaperLedger


class AtomicRiskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = PaperLedger(Path(self.temp.name) / "paper.sqlite", starting_cash="1000.00")
        self.now = datetime(2026, 11, 14, tzinfo=timezone.utc)
        self.limits = dict(max_order_dollars="100.00", max_position_dollars="150.00",
                           max_daily_loss_dollars="25.00", daily_realized_pnl="0.00")

    def fill(self, event, price="50.00", quantity=1, side="BUY", **changes):
        limits = dict(self.limits)
        limits.update(changes)
        return self.ledger.record_fill(event_id=event, timestamp=self.now, symbol="SPY",
                                       side=side, quantity=quantity, price=price, **limits)

    def test_valid_and_persistent(self):
        self.assertTrue(self.fill("first"))
        self.assertEqual(self.ledger.snapshot()["cash"], "950.00")
        reopened = PaperLedger(Path(self.temp.name) / "paper.sqlite", starting_cash="1000.00")
        self.assertEqual(reopened.snapshot()["fill_count"], 1)

    def test_order_and_position_caps(self):
        self.fill("first", price="75.00")
        with self.assertRaises(ValueError):
            self.fill("over-order", price="101.00")
        with self.assertRaises(ValueError):
            self.fill("over-position", price="80.00")
        self.assertEqual(self.ledger.snapshot()["fill_count"], 1)

    def test_daily_loss_and_missing_limits_fail_closed(self):
        with self.assertRaises(ValueError):
            self.fill("loss", daily_realized_pnl="-25.00")
        with self.assertRaises(ValueError):
            self.fill("missing", max_position_dollars=None)
        self.assertEqual(self.ledger.snapshot()["fill_count"], 0)

    def test_fee_included_in_order_cap(self):
        with self.assertRaises(ValueError):
            self.ledger.record_fill(event_id="fee", timestamp=self.now, symbol="SPY",
                                    side="BUY", quantity=1, price="100.00", fee="0.01",
                                    **self.limits)
        self.assertEqual(self.ledger.snapshot()["cash"], "1000.00")


if __name__ == "__main__":
    unittest.main()
