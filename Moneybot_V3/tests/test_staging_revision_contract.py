"""Offline regression: a live staging response must identify the requested revision."""
import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

script = Path(__file__).resolve().parents[1] / "staging_smoke.py"
spec = importlib.util.spec_from_file_location("v3_revision_smoke", script)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

COMMIT = "a" * 40
OTHER = "b" * 40
BASE = "https://moneybot-v3-staging.onrender.com"


def response(path):
    data = {
        "/healthz": (200, {"service": "up", "trading_state": "NOT_ACTIVATED"}),
        "/status": (200, {
            "application": "Moneybot V3", "trading_state": "NOT_ACTIVATED",
            "automatic_paper_trading": False, "real_money_trading": False,
            "market_data": "NOT_CONNECTED", "persistent_paper_ledger": "NOT_CONNECTED",
            "execution_time_risk_gate": "NOT_CONNECTED",
        }),
        "/readyz": (503, {"ready_for_automatic_paper_trading": False}),
        "/version": (200, {"git_commit": OTHER}),
    }
    if path.startswith("/paper-"):
        return 503, {"available": False}
    return data[path]


class StagingRevisionTests(TestCase):
    def test_rejects_stale_deployment_even_when_all_other_checks_pass(self):
        with patch.object(smoke, "verify_dashboard_html"), patch.object(
            smoke, "fetch", side_effect=lambda base, path: response(path)
        ):
            with self.assertRaisesRegex(ValueError, "revision does not match"):
                smoke.verify(BASE, COMMIT)

    def test_accepts_exact_revision_without_trading_activation(self):
        with patch.object(smoke, "verify_dashboard_html"), patch.object(
            smoke, "fetch", side_effect=lambda base, path: response(path)
        ):
            smoke.verify(BASE, OTHER)
