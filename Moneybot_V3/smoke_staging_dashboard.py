"""Read-only deployed V3 dashboard smoke test; never submits trading requests.

Usage: python Moneybot_V3/smoke_staging_dashboard.py https://moneybot-v3-staging.onrender.com
Only run against the isolated V3 staging service. Nonzero exit on any mismatch.
"""
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RejectRedirects(HTTPRedirectHandler):
    """Never follow a response to another origin during a staging smoke check."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(RejectRedirects)


def fetch(base, path):
    request = Request(base + path, headers={"Accept": "application/json"})
    try:
        with _OPENER.open(request, timeout=12) as response:
            return response.status, response.read(1024 * 1024).decode("utf-8")
    except HTTPError as error:
        return error.code, error.read(1024 * 1024).decode("utf-8")


def check(base, expected_commit=None):
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or parsed.hostname != "moneybot-v3-staging.onrender.com"
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.port is not None):
        raise ValueError("Only the canonical HTTPS V3 staging origin is allowed")
    base = "https://moneybot-v3-staging.onrender.com"
    status, page = fetch(base, "/")
    if status != 200 or not all(label in page for label in (
        "System health", "Account state", "Paper trades", "Risk limits",
        "Performance", "NOT ACTIVATED", "no demo balances",
    )):
        raise AssertionError("Dashboard HTML missing required safety or usability sections")
    status, health = fetch(base, "/healthz")
    if status != 200 or json.loads(health) != {
        "service": "up", "trading_state": "NOT_ACTIVATED"
    }:
        raise AssertionError("Liveness or activation state mismatch")
    status, state = fetch(base, "/status")
    data = json.loads(state)
    if status != 200 or not (
        data.get("trading_state") == "NOT_ACTIVATED"
        and data.get("automatic_paper_trading") is False
        and data.get("real_money_trading") is False
        and data.get("market_data") == "NOT_CONNECTED"
        and data.get("persistent_paper_ledger") == "NOT_CONNECTED"
        and data.get("execution_time_risk_gate") == "NOT_CONNECTED"
    ):
        raise AssertionError("Unexpected trading integration state")
    status, readiness = fetch(base, "/readyz")
    if status != 503 or json.loads(readiness).get("ready_for_automatic_paper_trading") is not False:
        raise AssertionError("Readiness incorrectly claims automatic paper trading")
    status, version = fetch(base, "/version")
    revision = json.loads(version).get("git_commit")
    if status != 200 or not isinstance(revision, str) or len(revision) != 40 or any(
        c not in "0123456789abcdef" for c in revision
    ):
        raise AssertionError("Cannot establish deployed Git revision")
    if expected_commit and revision != expected_commit:
        raise AssertionError(f"Deployed {revision}, expected {expected_commit}")
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Canonical V3 staging HTTPS URL")
    parser.add_argument("--expected-commit", help="Expected 40-character Git SHA")
    args = parser.parse_args()
    try:
        revision = check(args.url.rstrip("/"), args.expected_commit)
    except (AssertionError, ValueError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: V3 staging smoke test: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: read-only V3 staging smoke test; revision={revision}; paper trading NOT READY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
