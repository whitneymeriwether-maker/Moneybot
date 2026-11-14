"""Offline paper risk decision contract tests; no orders or network."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_decision_gate import paper_decision


class DecisionGateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
        self.args = dict(quote={"symbol": "SPY", "timestamp": self.now, "price": "50.00"},
                         provider="alpaca", authenticated=True, symbol="SPY",
                         now=self.now, account={"cash": "1000.00", "positions": {},
                                                "fill_count": 0},
                         side="BUY", quantity=1, market_open=True)

    def test_candidate_cannot_authorize_execution(self):
        result = paper_decision(**self.args)
        self.assertTrue(result["candidate_only"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["requires_atomic_execution_recheck"])

    def test_fail_closed_on_market_and_auth(self):
        for change in ({"market_open": False}, {"authenticated": False},
                       {"quote": {"symbol": "SPY", "timestamp": self.now - timedelta(minutes=3), "price": "50.00"}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                paper_decision(**{**self.args, **change})

    def test_cash_order_position_and_loss_limits(self):
        for change in ({"account": {"cash": "10.00", "positions": {}, "fill_count": 0}},
                       {"quantity": 3}, {"max_order_dollars": "40.00"},
                       {"max_position_dollars": "40.00"},
                       {"daily_realized_pnl": "-25.00"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                paper_decision(**{**self.args, **change})

    def test_sell_requires_owned_shares(self):
        with self.assertRaises(ValueError):
            paper_decision(**{**self.args, "side": "SELL"})
        owned = {"cash": "0.00", "positions": {"SPY": {"quantity": 2, "cost_basis": "80.00"}}, "fill_count": 1}
        result = paper_decision(**{**self.args, "side": "SELL", "account": owned})
        self.assertEqual(result["side"], "SELL")

    def test_rejects_inconsistent_position(self):
        bad = {"cash": "100.00", "positions": {"SPY": {"quantity": 0, "cost_basis": "50.00"}}, "fill_count": 1}
        with self.assertRaises(ValueError):
            paper_decision(**{**self.args, "account": bad})


if __name__ == "__main__":
    unittest.main()
