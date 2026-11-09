"""Offline regression tests for the read-only staging smoke check."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parent / "smoke_staging.py"
spec = importlib.util.spec_from_file_location("v3_smoke_staging", MODULE_PATH)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeStagingTests(unittest.TestCase):
    def test_rejects_insecure_remote_origin_before_network(self):
        with patch.object(smoke, "fetch", side_effect=AssertionError("network called")):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                smoke.check("http://example.com")

    def test_rejects_embedded_credentials_before_network(self):
        with patch.object(smoke, "fetch", side_effect=AssertionError("network called")):
            with self.assertRaisesRegex(ValueError, "bare HTTP"):
                smoke.check("https://user:secret@example.com")

    def test_rejects_query_and_path_before_network(self):
        with patch.object(smoke, "fetch", side_effect=AssertionError("network called")):
            for origin in ("https://example.com/admin", "https://example.com/?x=1"):
                with self.subTest(origin=origin):
                    with self.assertRaisesRegex(ValueError, "bare HTTP"):
                        smoke.check(origin)

    def test_rejects_missing_dashboard_markers(self):
        with patch.object(smoke, "fetch", return_value=(200, {}, b"Moneybot V3")):
            with self.assertRaisesRegex(AssertionError, "Dashboard missing"):
                smoke.check("https://example.com")

    def test_rejects_missing_revision_provenance(self):
        sha = "a" * 40
        html = b"Moneybot V3 System health Account state Paper trades Risk limits Performance NOT ACTIVATED no demo balances"
        responses = iter([
            (200, {}, html),
            (200, {}, b'{"service":"up","trading_state":"NOT_ACTIVATED"}'),
            (503, {}, b'{"ready_for_automatic_paper_trading":false}'),
            (200, {}, b'{"automatic_paper_trading":false,"real_money_trading":false,"trading_state":"NOT_ACTIVATED","market_data":"NOT_CONNECTED","persistent_paper_ledger":"NOT_CONNECTED","execution_time_risk_gate":"NOT_CONNECTED"}'),
            (200, {}, b'{"git_commit":null}'),
        ])
        with patch.object(smoke, "fetch", side_effect=lambda *args: next(responses)):
            with self.assertRaisesRegex(AssertionError, "Wrong deployed revision"):
                smoke.check("https://example.com", sha)


if __name__ == "__main__":
    unittest.main()
