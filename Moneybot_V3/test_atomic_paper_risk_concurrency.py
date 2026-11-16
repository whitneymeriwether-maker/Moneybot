"""Regression: concurrent hypothetical fills cannot overspend the isolated ledger.

This tests the SQLite writer lock and transaction-time risk limits; it does
not authenticate quotes or authorize automated execution.
"""
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from Moneybot_V3.paper_ledger import PaperLedger


class AtomicPaperRiskTests(unittest.TestCase):
    def test_concurrent_buys_only_one_can_consume_cash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.sqlite3"
            PaperLedger(path, starting_cash="100.00")
            barrier = threading.Barrier(2)
            outcomes = []
            lock = threading.Lock()

            def buyer(event_id):
                ledger = PaperLedger(path, starting_cash="100.00")
                barrier.wait(timeout=10)
                try:
                    outcome = ledger.record_fill(
                        event_id=event_id,
                        timestamp=datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc),
                        symbol="AAPL", side="BUY", quantity=1, price="75.00",
                        max_order_dollars="80.00",
                        max_position_dollars="100.00",
                        max_daily_loss_dollars="50.00",
                        daily_realized_pnl="0.00",
                    )
                except ValueError:
                    outcome = "rejected"
                with lock:
                    outcomes.append(outcome)

            workers = [threading.Thread(target=buyer, args=(f"race-{i}",))
                       for i in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=15)
                self.assertFalse(worker.is_alive(), "paper ledger writer deadlocked")

            self.assertEqual(sorted(map(str, outcomes)), ["True", "rejected"])
            ledger = PaperLedger.open_readonly(path)
            snapshot = ledger.snapshot()
            self.assertEqual(snapshot["cash"], "25.00")
            self.assertEqual(snapshot["fill_count"], 1)
            self.assertEqual(snapshot["positions"]["AAPL"]["quantity"], 1)
            self.assertEqual(ledger.audit_history()["audited_fills"], 1)


if __name__ == "__main__":
    unittest.main()
