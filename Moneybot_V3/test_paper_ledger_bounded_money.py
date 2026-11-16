"""Reject pathological or noncanonical money input before SQLite writes."""
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from Moneybot_V3.paper_ledger import PaperLedger


class BoundedMoneyTests(unittest.TestCase):
    def test_rejected_money_inputs_leave_ledger_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PaperLedger(Path(directory) / "paper.sqlite3", starting_cash="100.00")
            baseline = ledger.snapshot()
            payload = dict(
                event_id="bounded-input", timestamp=datetime(2026, 11, 16, tzinfo=timezone.utc),
                symbol="AAPL", side="BUY", quantity=1,
            )
            for value in ("9" * 100000, "1e2", "1.000", "-1", " 1.00", "01.00", "NaN", "Infinity"):
                with self.subTest(value=value[:40]):
                    with self.assertRaises(ValueError):
                        ledger.record_fill(**payload, price=value)
                    self.assertEqual(ledger.snapshot(), baseline)

    def test_canonical_cents_still_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PaperLedger(Path(directory) / "paper.sqlite3", starting_cash="100.00")
            self.assertTrue(ledger.record_fill(
                event_id="canonical-fill", timestamp=datetime(2026, 11, 16, tzinfo=timezone.utc),
                symbol="AAPL", side="BUY", quantity=1, price="1.25", fee="0.01",
            ))
            self.assertEqual(ledger.snapshot()["cash"], "98.74")


if __name__ == "__main__":
    unittest.main()
