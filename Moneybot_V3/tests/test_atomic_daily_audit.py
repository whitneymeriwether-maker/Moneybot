import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from Moneybot_V3.paper_ledger import PaperLedger


class AtomicDailyAuditTests(unittest.TestCase):
    def test_recorded_loss_blocks_buy_without_external_pnl(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = PaperLedger(Path(tmp) / "paper.sqlite")
            now = datetime(2026, 11, 17, 15, tzinfo=timezone.utc)
            ledger.record_fill(event_id="buy", timestamp=now, symbol="SPY",
                               side="BUY", quantity=1, price="100.00")
            ledger.record_fill(event_id="sell", timestamp=now, symbol="SPY",
                               side="SELL", quantity=1, price="80.00")
            args = dict(event_id="next", timestamp=now, symbol="SPY",
                        side="BUY", quantity=1, price="80.00",
                        max_order_dollars="100.00", max_position_dollars="200.00",
                        max_daily_loss_dollars="10.00",
                        audit_daily_inside_transaction=True)
            before = ledger.snapshot()
            with self.assertRaisesRegex(ValueError, "Daily paper loss"):
                ledger.record_fill(**args)
            with self.assertRaises(ValueError):
                ledger.record_fill(**args, daily_realized_pnl="0.00")
            self.assertEqual(ledger.snapshot(), before)
            args["timestamp"] = now + timedelta(days=1)
            self.assertTrue(ledger.record_fill(**args))
            self.assertEqual(ledger.audit_history()["audited_fills"], 3)


if __name__ == "__main__":
    unittest.main()
