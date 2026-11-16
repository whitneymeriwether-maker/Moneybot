"""Offline tests: preview never records fills or trusts unaudited account state."""
import unittest
from datetime import datetime, timezone, timedelta
from Moneybot_V3.paper_execution_preview import preview_paper_buy
from Moneybot_V3.paper_risk_preflight import PaperRiskRejected

NOW = datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc)


class LedgerStub:
    def __init__(self, *, cash="1000.00", shares=1, mismatch=False):
        self.cash, self.shares, self.mismatch = cash, shares, mismatch
        self.writes = 0

    def audit_history(self):
        return {"audited_fills": 2 if self.mismatch else 1,
                "cash": self.cash, "realized_pnl": "0.00"}

    def snapshot(self):
        return {"fill_count": 1, "cash": self.cash,
                "realized_pnl": "0.00",
                "positions": {"AAPL": {"quantity": self.shares}}}

    def record_fill(self, **kwargs):
        self.writes += 1
        raise AssertionError("preview must not record fills")


def preview(ledger, **changes):
    args = dict(
        ledger=ledger,
        quote={"symbol": "AAPL", "price": "100.00",
               "timestamp_utc": (NOW - timedelta(seconds=5)).isoformat(),
               "provider": "alpaca", "authenticated_transport": True,
               "provider_verified": True},
        symbol="AAPL", quantity="2", max_order_notional="500.00",
        max_position_notional="400.00", paper_only=True,
        kill_switch=False, now=NOW)
    args.update(changes)
    return preview_paper_buy(**args)


class PreviewTests(unittest.TestCase):
    def test_audited_account_preview_never_mutates(self):
        ledger = LedgerStub()
        result = preview(ledger)
        self.assertEqual(result["status"], "preflight_only_not_executed")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["ledger_mutated"])
        self.assertEqual(ledger.writes, 0)

    def test_fails_closed_on_risk_and_bad_ledger(self):
        for ledger, changes in (
            (LedgerStub(cash="199.00"), {}),
            (LedgerStub(shares=3), {}),
            (LedgerStub(mismatch=True), {}),
            (LedgerStub(), {"kill_switch": True}),
            (LedgerStub(), {"paper_only": False}),
            (LedgerStub(), {"quote": {"symbol": "AAPL"}}),
        ):
            with self.subTest(changes=changes, ledger=ledger.__dict__):
                with self.assertRaises(PaperRiskRejected):
                    preview(ledger, **changes)
                self.assertEqual(ledger.writes, 0)


if __name__ == "__main__":
    unittest.main()
