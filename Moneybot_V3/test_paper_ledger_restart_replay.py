"""Restart/idempotency regression for the disconnected hypothetical SQLite ledger.

This does not enable any automated execution or validate market-data provenance.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from Moneybot_V3.paper_ledger import PaperLedger


class RestartReplayTests(unittest.TestCase):
    def test_exact_retry_after_reopen_is_not_double_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account.sqlite3"
            timestamp = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)
            payload = dict(
                event_id="restart-fill-1", timestamp=timestamp,
                symbol="AAPL", side="BUY", quantity=2, price="25.00",
                max_order_dollars="60.00",
                max_position_dollars="100.00",
                max_daily_loss_dollars="20.00",
                daily_realized_pnl="0.00",
            )
            ledger = PaperLedger(path, starting_cash="100.00")
            self.assertTrue(ledger.record_fill(**payload))
            del ledger

            restarted = PaperLedger(path, starting_cash="100.00")
            self.assertFalse(restarted.record_fill(**payload))
            snapshot = restarted.snapshot()
            self.assertEqual(snapshot["cash"], "50.00")
            self.assertEqual(snapshot["fill_count"], 1)
            self.assertEqual(snapshot["positions"]["AAPL"]["quantity"], 2)
            self.assertEqual(restarted.audit_history()["audited_fills"], 1)

            with self.assertRaisesRegex(ValueError, "Conflicting paper fill event ID"):
                restarted.record_fill(**{**payload, "quantity": 1})
            self.assertEqual(restarted.snapshot(), snapshot)

    def test_restart_refuses_different_seed_cash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account.sqlite3"
            PaperLedger(path, starting_cash="100.00")
            with self.assertRaises(ValueError):
                PaperLedger(path, starting_cash="1000.00")
            self.assertEqual(PaperLedger.open_readonly(path).snapshot()["cash"], "100.00")


if __name__ == "__main__":
    unittest.main()
