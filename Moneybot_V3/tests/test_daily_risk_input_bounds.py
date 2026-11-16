"""Regression checks for bounded execution-time paper risk input."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from Moneybot_V3.paper_ledger import PaperLedger


class DailyRiskInputTests(unittest.TestCase):
    def test_malformed_daily_pnl_fails_without_mutating_account(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PaperLedger(Path(directory) / "paper.sqlite", starting_cash="100.00")
            before = ledger.snapshot()
            for index, pnl in enumerate((
                "9" * 100000, "1e100000", "0.001", "NaN", "Infinity",
                "--1.00", "+1.00", " 1.00", "01.00", "-0.000",
            )):
                with self.subTest(pnl=str(pnl)[:30]):
                    with self.assertRaises(ValueError):
                        ledger.record_fill(
                            event_id=f"malformed-{index}",
                            timestamp=datetime.now(timezone.utc),
                            symbol="TEST", side="BUY", quantity=1,
                            price="1.00", max_order_dollars="50.00",
                            max_position_dollars="50.00",
                            max_daily_loss_dollars="10.00",
                            daily_realized_pnl=pnl,
                        )
                    self.assertEqual(ledger.snapshot(), before)

    def test_signed_cent_pnl_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PaperLedger(Path(directory) / "paper.sqlite", starting_cash="100.00")
            self.assertTrue(ledger.record_fill(
                event_id="valid-negative-pnl",
                timestamp=datetime.now(timezone.utc),
                symbol="TEST", side="BUY", quantity=1,
                price="1.00", max_order_dollars="50.00",
                max_position_dollars="50.00",
                max_daily_loss_dollars="10.00",
                daily_realized_pnl="-1.25",
            ))
            self.assertEqual(ledger.snapshot()["cash"], "99.00")


if __name__ == "__main__":
    unittest.main()
