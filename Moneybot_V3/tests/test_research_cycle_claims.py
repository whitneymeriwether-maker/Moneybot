"""Contract tests for restart-safe, non-executing research cycle claims."""
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_cycle_claims import ResearchCycleClaims


class ResearchClaimsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "cycles.sqlite"
        self.now = datetime(2026, 11, 14, tzinfo=timezone.utc)

    def test_claim_survives_restart_and_completion(self):
        claims = ResearchCycleClaims(self.path)
        self.assertTrue(claims.claim("SPY:20261114T1200", now=self.now))
        self.assertFalse(ResearchCycleClaims(self.path).claim("SPY:20261114T1200", now=self.now))
        claims.finish("SPY:20261114T1200", succeeded=True)
        self.assertFalse(ResearchCycleClaims(self.path).claim("SPY:20261114T1200", now=self.now))
        with self.assertRaises(ValueError):
            claims.finish("SPY:20261114T1200", succeeded=True)

    def test_failed_and_abandoned_claims_not_replayed(self):
        claims = ResearchCycleClaims(self.path)
        self.assertTrue(claims.claim("cycle-a", now=self.now))
        claims.finish("cycle-a", succeeded=False)
        self.assertFalse(ResearchCycleClaims(self.path).claim("cycle-a", now=self.now))
        self.assertTrue(claims.claim("cycle-b", now=self.now))
        self.assertFalse(ResearchCycleClaims(self.path).claim("cycle-b", now=self.now))

    def test_parallel_workers_cannot_double_claim(self):
        ResearchCycleClaims(self.path)
        def worker(_):
            return ResearchCycleClaims(self.path).claim("cycle-concurrent", now=self.now)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(worker, range(12)))
        self.assertEqual(results.count(True), 1)

    def test_invalid_inputs_rejected(self):
        claims = ResearchCycleClaims(self.path)
        for key in ("", "../invalid", "x" * 101):
            with self.assertRaises(ValueError):
                claims.claim(key, now=self.now)
        with self.assertRaises(ValueError):
            claims.claim("valid", now=datetime(2026, 11, 14))
        with self.assertRaises(ValueError):
            claims.finish("valid", succeeded=1)


if __name__ == "__main__":
    unittest.main()
