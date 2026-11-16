"""Offline regression tests for fail-closed paper proposal preflight."""
import unittest
from datetime import datetime, timezone, timedelta
from Moneybot_V3.paper_risk_preflight import check_paper_buy, PaperRiskRejected


NOW = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)


def proposal(**changes):
    args = dict(
        quote={"symbol": "AAPL", "price": "100.00",
               "timestamp_utc": (NOW - timedelta(seconds=10)).isoformat(),
               "provider": "alpaca", "authenticated_transport": True,
               "provider_verified": True},
        symbol="AAPL", quantity="2", available_cash="1000.00",
        max_order_notional="500.00", max_position_notional="800.00",
        existing_position_notional="100.00",
        paper_only=True, kill_switch=False, now=NOW)
    args.update(changes)
    return args


class RiskPreflightTests(unittest.TestCase):
    def test_valid_proposal_is_not_a_fill(self):
        result = check_paper_buy(**proposal())
        self.assertEqual(result["status"], "preflight_only_not_executed")
        self.assertEqual(result["reference_notional"], "200.00")

    def test_fail_closed_limits(self):
        for changes in (
            {"paper_only": False}, {"kill_switch": True},
            {"available_cash": "199"}, {"max_order_notional": "199"},
            {"max_position_notional": "299"},
            {"quantity": "NaN"}, {"quantity": "-1"}, {"quantity": 2},
            {"available_cash": None}, {"existing_position_notional": "-1"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(PaperRiskRejected):
                    check_paper_buy(**proposal(**changes))

    def test_stale_or_unauthenticated_quote_rejected(self):
        for change in (
            {"authenticated_transport": False},
            {"provider_verified": False},
            {"timestamp_utc": (NOW - timedelta(minutes=4)).isoformat()},
            {"symbol": "MSFT"},
        ):
            quote = proposal()["quote"].copy()
            quote.update(change)
            with self.subTest(change=change):
                with self.assertRaises(PaperRiskRejected):
                    check_paper_buy(**proposal(quote=quote))


if __name__ == "__main__":
    unittest.main()
