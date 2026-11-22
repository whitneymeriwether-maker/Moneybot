"""Independent deployed HTTP smoke test for the isolated V3 staging dashboard.

Usage: python Moneybot_V3/smoke_deployed.py https://moneybot-v3-staging.onrender.com
Never submits orders, writes account data, or treats liveness as trading readiness.
"""
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def check(base):
    parsed = urlparse(base)
    if parsed.scheme != "https" or parsed.hostname != "moneybot-v3-staging.onrender.com" or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Only the isolated V3 HTTPS staging origin is permitted")
    def get(path):
        req = Request(base.rstrip("/") + path, headers={"Cache-Control": "no-cache", "User-Agent": "Moneybot-V3-readonly-smoke/1"})
        try:
            with urlopen(req, timeout=35) as response:
                return response.status, dict(response.headers), response.read(300000)
        except HTTPError as error:
            return error.code, dict(error.headers), error.read(300000)

    status, headers, html = get("/")
    assert status == 200 and b"System health" in html and b"NOT ACTIVATED" in html
    assert b"Account state" in html and b"Paper trades" in html and b"Risk limits" in html and b"Performance" in html
    assert headers.get("Cache-Control") == "no-store"
    status, _, raw = get("/healthz")
    assert status == 200 and json.loads(raw)["trading_state"] == "NOT_ACTIVATED"
    status, _, raw = get("/status")
    state = json.loads(raw)
    assert status == 200 and state["automatic_paper_trading"] is False and state["real_money_trading"] is False
    assert state["market_data"] == "NOT_CONNECTED" and state["execution_time_risk_gate"] == "NOT_CONNECTED"
    status, _, raw = get("/readyz")
    assert status == 503 and json.loads(raw)["ready_for_automatic_paper_trading"] is False
    status, _, raw = get("/version")
    revision = json.loads(raw).get("git_commit")
    assert status == 200 and isinstance(revision, str) and len(revision) == 40 and all(c in "0123456789abcdef" for c in revision), "Deployed revision not verifiable"
    for path in ("/paper-account", "/paper-journal-activity", "/paper-ledger-summary", "/paper-ledger-positions", "/paper-ledger-fills"):
        status, headers, raw = get(path)
        assert status in (200, 503), (path, status)
        assert headers.get("Cache-Control") == "no-store", path
        data = json.loads(raw)
        if status == 503:
            assert data.get("available") is False, path
        else:
            assert data.get("available") is True and data.get("trading_ready") is False, path
            assert data.get("source") in ("isolated_paper_journal", "local_hypothetical_sqlite_ledger"), path
            assert data.get("verification") in ("journal_only_not_broker_or_market_verified", "audited_local_records_not_broker_verified"), path
    print("PASS: deployed V3 dashboard, disabled trading, isolated data labeling; revision", revision)
    print("NOTE: read-only HTTP smoke is not browser rendering, paper execution, or ledger durability validation")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("Usage: smoke_deployed.py https://moneybot-v3-staging.onrender.com")
        check(sys.argv[1])
    except (AssertionError, ValueError, URLError, OSError, KeyError, json.JSONDecodeError) as exc:
        print("FAIL: V3 deployed smoke:", repr(exc), file=sys.stderr)
        sys.exit(1)
