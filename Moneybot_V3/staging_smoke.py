"""Read-only external staging smoke test; no order or mutation requests.

Run: python Moneybot_V3/staging_smoke.py https://moneybot-v3-staging.onrender.com
Exits nonzero on missing, inconsistent, or unsafe staging responses.
"""
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("staging: redirects are forbidden")


OPENER = build_opener(RejectRedirects)


def fetch(base, path):
    req = Request(base + path, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    try:
        with OPENER.open(req, timeout=15) as response:
            status = response.status
            body = response.read(131073)
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        status = exc.code
        body = exc.read(131073)
        content_type = exc.headers.get("Content-Type", "")
    if len(body) > 131072:
        raise ValueError(path + ": response too large")
    if "application/json" not in content_type:
        raise ValueError(path + ": unexpected content type")
    return status, json.loads(body)


def verify_dashboard_html(base):
    """Check the actual served dashboard, not just JSON health endpoints."""
    req = Request(base + "/", headers={"Accept": "text/html", "Cache-Control": "no-cache"})
    with OPENER.open(req, timeout=15) as response:
        if response.status != 200 or "text/html" not in response.headers.get("Content-Type", ""):
            raise ValueError("dashboard: unexpected HTTP status or content type")
        payload = response.read(262145)
    if len(payload) > 262144:
        raise ValueError("dashboard: response too large")
    html = payload.decode("utf-8")
    for marker in (
        "<title>Moneybot V3", "System health", "Account state",
        "Paper trades", "Risk limits", "Performance", "Integration status",
        "Actual state only", "NOT ACTIVATED",
        "Recent hypothetical fills (NOT broker trades)",
        'id="service-health"', 'id="readiness-health"',
        'id="paper-account-state"', 'id="hypothetical-fill-rows"',
        'id="offline-realized-pnl"', 'id="integration-health"',
        'id="deployed-revision"', "refreshHealth();",
    ):
        if marker not in html:
            raise ValueError("dashboard: missing required content " + marker)


def verify(base):
    parsed = urlsplit(base)
    if parsed.scheme != "https" or parsed.netloc != "moneybot-v3-staging.onrender.com" or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Only the exact isolated HTTPS staging origin is allowed")
    verify_dashboard_html(base)
    status, health = fetch(base, "/healthz")
    if not (status == 200 and health.get("service") == "up" and health.get("trading_state") == "NOT_ACTIVATED"):
        raise ValueError("liveness contract failed")
    status, state = fetch(base, "/status")
    if not (status == 200 and state.get("application") == "Moneybot V3"):
        raise ValueError("status unavailable")
    if not (state.get("trading_state") == "NOT_ACTIVATED" and state.get("automatic_paper_trading") is False and state.get("real_money_trading") is False):
        raise ValueError("unexpected trading activation")
    if not all(state.get(k) == "NOT_CONNECTED" for k in ("market_data", "persistent_paper_ledger", "execution_time_risk_gate")):
        raise ValueError("unexpected integration state")
    status, readiness = fetch(base, "/readyz")
    if not (status == 503 and readiness.get("ready_for_automatic_paper_trading") is False):
        raise ValueError("readiness must fail closed")
    for path in ("/paper-account", "/paper-journal-activity", "/paper-ledger-summary", "/paper-ledger-fills"):
        status, data = fetch(base, path)
        if status == 503:
            if data.get("available") is not False:
                raise ValueError(path + ": missing explicit unavailable flag")
        elif status == 200:
            if not (data.get("available") is True and data.get("trading_ready") is False):
                raise ValueError(path + ": invalid offline record state")
        else:
            raise AssertionError(path + ": unexpected HTTP " + str(status))
    status, version = fetch(base, "/version")
    if not (status == 200 and isinstance(version.get("git_commit"), str) and len(version["git_commit"]) == 40):
        raise ValueError("missing deployment provenance")
    print("PASS: staging read-only HTTP contract, revision", version["git_commit"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: staging_smoke.py https://moneybot-v3-staging.onrender.com")
    try:
        verify(sys.argv[1].rstrip("/"))
    except (AssertionError, ValueError, URLError, TimeoutError, OSError) as exc:
        sys.exit("FAIL: " + str(exc))
