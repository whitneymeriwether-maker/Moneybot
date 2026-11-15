"""Contract tests for the external staging smoke verifier.

These tests run entirely offline and must never contact staging or any broker.
"""
import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "staging_smoke.py"
spec = importlib.util.spec_from_file_location("v3_staging_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class StagingSmokeSafetyTests(unittest.TestCase):
    def test_rejects_other_origins_without_network(self):
        for origin in (
            "http://moneybot-v3-staging.onrender.com",
            "https://evil.example",
            "https://moneybot-v3-staging.onrender.com.evil.example",
            "https://moneybot-v3-staging.onrender.com@evil.example",
            "https://moneybot-v3-staging.onrender.com/path",
            "https://moneybot-v3-staging.onrender.com?unsafe=1",
        ):
            with self.subTest(origin=origin), patch.object(smoke, "verify_dashboard_html") as dashboard:
                with self.assertRaises(ValueError):
                    smoke.verify(origin)
                dashboard.assert_not_called()

    def test_readiness_cannot_be_green_without_verified_activation(self):
        responses = {
            "/healthz": (200, {"service": "up", "trading_state": "NOT_ACTIVATED"}),
            "/status": (200, {
                "application": "Moneybot V3", "trading_state": "NOT_ACTIVATED",
                "automatic_paper_trading": False, "real_money_trading": False,
                "market_data": "NOT_CONNECTED", "persistent_paper_ledger": "NOT_CONNECTED",
                "execution_time_risk_gate": "NOT_CONNECTED",
            }),
            "/readyz": (200, {"ready_for_automatic_paper_trading": True}),
        }
        with patch.object(smoke, "verify_dashboard_html"), patch.object(
            smoke, "fetch", side_effect=lambda base, path: responses[path]
        ):
            with self.assertRaises(ValueError):
                smoke.verify("https://moneybot-v3-staging.onrender.com")

    def test_live_orders_flag_fails_closed(self):
        responses = {
            "/healthz": (200, {"service": "up", "trading_state": "NOT_ACTIVATED"}),
            "/status": (200, {
                "application": "Moneybot V3", "trading_state": "NOT_ACTIVATED",
                "automatic_paper_trading": False, "real_money_trading": True,
            }),
        }
        with patch.object(smoke, "verify_dashboard_html"), patch.object(
            smoke, "fetch", side_effect=lambda base, path: responses[path]
        ):
            with self.assertRaises(ValueError):
                smoke.verify("https://moneybot-v3-staging.onrender.com")


if __name__ == "__main__":
    unittest.main()
