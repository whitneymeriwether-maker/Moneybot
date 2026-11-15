"""Regression: the staging UI must disclose refresh attempts without implying data freshness."""
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "paper_status_server.py"

class DashboardRefreshTimestampContract(unittest.TestCase):
    def test_timestamp_is_attempt_not_verified_market_freshness(self):
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn('id="snapshot-time"', source)
        self.assertIn('Snapshot not yet checked · data freshness unknown', source)
        self.assertIn('Last refresh attempt (UTC): ', source)
        self.assertIn('failed endpoints remain unverified', source)
        self.assertIn('new Date().toISOString()', source)
        self.assertIn('refreshInProgress = false;', source)

if __name__ == "__main__":
    unittest.main()
