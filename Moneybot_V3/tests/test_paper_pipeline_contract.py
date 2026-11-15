"""Cross-component offline smoke: synthetic data, never broker execution."""
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_ledger import PaperLedger
from paper_decision_gate import paper_decision
from research_cycle_claims import ResearchCycleClaims


class PaperPipelineContract(unittest.TestCase):
    def test_claim_candidate_atomic_ledger_restart_and_duplicate(self):
        with tempfile.TemporaryDirectory() as root:
            ledger_path = str(Path(root) / "ledger.sqlite")
            cycle_path = str(Path(root) / "cycles.sqlite")
            ledger = PaperLedger(ledger_path)
            claims = ResearchCycleClaims(cycle_path)
            now = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
            self.assertTrue(claims.claim("SPY:20261113T1500", now=now))
            self.assertFalse(ResearchCycleClaims(cycle_path).claim("SPY:20261113T1500", now=now))
            snapshot = ledger.snapshot()
            quote = {"symbol": "SPY", "timestamp": now - timedelta(seconds=5), "price": "50.00"}
            candidate = paper_decision(
                quote=quote, provider="alpaca", authenticated=True,
                symbol="SPY", now=now, account={
                    "cash": snapshot["cash"], "positions": snapshot["positions"],
                    "fill_count": snapshot["fill_count"]},
                side="BUY", quantity=1, market_open=True,
                daily_realized_pnl="0.00")
            self.assertFalse(candidate["execution_authorized"])
            self.assertTrue(candidate["requires_atomic_execution_recheck"])
            # Synthetic fill is deliberately explicit: NOT a broker or authenticated
            # exchange fill. This verifies the isolated ledger accounting only.
            fill = dict(event_id="synthetic:SPY:20261113T1500", timestamp=now,
                        symbol="SPY", side="BUY", quantity=1, price="50.00",
                        max_order_dollars="100.00", max_position_dollars="250.00",
                        max_daily_loss_dollars="25.00", daily_realized_pnl="0.00")
            self.assertTrue(ledger.record_fill(**fill))
            self.assertFalse(PaperLedger(ledger_path).record_fill(**fill))
            with self.assertRaises(ValueError):
                ledger.record_fill(**{**fill, "event_id": "synthetic:blocked",
                                      "max_order_dollars": "10.00"})
            self.assertEqual(PaperLedger.open_readonly(ledger_path).snapshot()["fill_count"], 1)
            self.assertEqual(ledger.audit_history()["audited_fills"], 1)
            claims.finish("SPY:20261113T1500", succeeded=True)
            self.assertFalse(ResearchCycleClaims(cycle_path).claim("SPY:20261113T1500", now=now))

    def test_unverified_market_observation_never_reaches_ledger(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = PaperLedger(str(Path(root) / "ledger.sqlite"))
            now = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
            quote = {"symbol": "SPY", "timestamp": now - timedelta(minutes=10), "price": "50.00"}
            with self.assertRaises(ValueError):
                paper_decision(quote=quote, provider="alpaca", authenticated=False,
                               symbol="SPY", now=now,
                               account={"cash": "1000.00", "positions": {}, "fill_count": 0},
                               side="BUY", quantity=1, market_open=True)
            self.assertEqual(ledger.snapshot()["fill_count"], 0)


if __name__ == "__main__":
    unittest.main()
