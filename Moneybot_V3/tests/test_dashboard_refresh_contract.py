"""Offline contract for browser polling serialization; never contacts staging."""
import unittest
from pathlib import Path


class DashboardRefreshContract(unittest.TestCase):
    def test_only_one_refresh_mutates_dashboard_at_a_time(self):
        source = (Path(__file__).resolve().parents[1] / "paper_status_server.py").read_text()
        html = source.split('_HTML = r"""', 1)[1].split('"""', 1)[0]
        start = html.index("async function refreshHealth() {")
        end = html.index("refreshHealth();", start)
        function = html[start:end]
        self.assertIn("let refreshInProgress = false;", html[:start])
        self.assertIn("if (refreshInProgress) return;", function)
        self.assertIn("refreshInProgress = true;", function)
        self.assertIn("finally {\n    refreshInProgress = false;", function)
        self.assertLess(function.index("refreshInProgress = true;"), function.index('fetch("/version"'))


if __name__ == "__main__":
    unittest.main()
