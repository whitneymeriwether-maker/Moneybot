"""Fail-closed HTTP smoke test for the isolated, read-only V3 dashboard.

Usage: python Moneybot_V3/smoke_dashboard.py https://moneybot-v3-staging.onrender.com
Requires no third-party dependencies. Does not submit orders or change state.
"""
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def check(base):
    if not (base.startswith("https://") or base.startswith("http://127.0.0.1:")):
        raise ValueError("Only HTTPS staging or local loopback URLs are accepted")
    base = base.rstrip("/")

    def request(path, method="GET"):
        req = Request(base + path, method=method, headers={"Cache-Control": "no-store"})
        try:
            with urlopen(req, timeout=15) as response:
                return response.status, response.headers, response.read()
        except HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def endpoint(path, expected):
        status, headers, body = request(path)
        assert status == expected, f"{path}: expected HTTP {expected}, got {status}"
        assert headers.get("Cache-Control") == "no-store", f"{path}: cache enabled"
        assert headers.get("X-Content-Type-Options") == "nosniff", f"{path}: nosniff missing"
        return body

    html = endpoint("/", 200).decode("utf-8")
    for label in ("System health", "Account state", "Paper trades", "Risk limits",
                  "Performance", "NOT ACTIVATED", "Refresh status now",
                  "Actual state only", "NOT broker"):
        assert label in html, f"Dashboard missing: {label}"
    health = json.loads(endpoint("/healthz", 200))
    assert health == {"service": "up", "trading_state": "NOT_ACTIVATED"}
    status = json.loads(endpoint("/status", 200))
    for key, expected in {
        "application": "Moneybot V3",
        "trading_state": "NOT_ACTIVATED",
        "automatic_paper_trading": False,
        "real_money_trading": False,
        "market_data": "NOT_CONNECTED",
        "persistent_paper_ledger": "NOT_CONNECTED",
        "execution_time_risk_gate": "NOT_CONNECTED",
    }.items():
        assert status.get(key) == expected, f"Unexpected {key}: {status.get(key)!r}"
    ready = json.loads(endpoint("/readyz", 503))
    assert ready.get("ready_for_automatic_paper_trading") is False
    version = json.loads(endpoint("/version", 200))
    assert version.get("git_commit") is None or (
        isinstance(version["git_commit"], str) and len(version["git_commit"]) == 40
        and all(c in "0123456789abcdef" for c in version["git_commit"])
    )
    # A missing optional ledger must be explicit, never fabricated as zero trades.
    for path in ("/paper-account", "/paper-journal-activity",
                 "/paper-ledger-summary", "/paper-ledger-positions",
                 "/paper-ledger-fills"):
        code, _, raw = request(path)
        assert code in (200, 503), f"{path}: unexpected HTTP {code}"
        data = json.loads(raw)
        assert data.get("available") is (code == 200), f"{path}: availability mismatch"
        if code == 200:
            assert data.get("trading_ready") is False, f"{path}: unsafe ready flag"
    # Safe negative test: no request body, no order; confirm state-changing verbs rejected.
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        code, _, _ = request("/orders", method)
        assert code == 405, f"{method} /orders returned {code}, expected 405"
    print("PASS: V3 dashboard HTTP contract, disclosures, fail-closed readiness and write rejection")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python Moneybot_V3/smoke_dashboard.py HTTPS_STAGING_URL")
    try:
        check(sys.argv[1])
    except (AssertionError, ValueError, URLError, OSError, json.JSONDecodeError) as exc:
        sys.exit(f"FAIL: {exc}")
