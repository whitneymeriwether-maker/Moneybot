"""Read-only external smoke check for an isolated Moneybot V3 staging deployment.

Usage: python Moneybot_V3/smoke_staging.py https://moneybot-v3-staging.onrender.com --revision SHA
No credentials or order endpoints are used. A green check does NOT authorize trading.
"""
import argparse
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    """Do not follow redirects away from the verified staging origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(NoRedirect)


def fetch(base, path, method="GET"):
    req = Request(base + path, headers={"Accept": "application/json, text/html"}, method=method)
    try:
        response = _OPENER.open(req, timeout=12)
    except HTTPError as error:
        response = error
    with response:
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError(path + ": response exceeds 1 MiB")
        return response.status, response.headers, body


def check(base, revision=None):
    parsed = urlsplit(base)
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Expected a bare HTTP(S) service origin")
    if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Remote smoke tests require HTTPS")
    base = base.rstrip("/")
    status, headers, body = fetch(base, "/")
    if "text/html" not in headers.get("Content-Type", "").lower():
        raise AssertionError("Dashboard must be served as HTML")
    if status != 200 or b"Moneybot V3" not in body:
        raise AssertionError("Dashboard HTML not available")
    for marker in (b"System health", b"Account state", b"Paper trades",
                   b"Risk limits", b"Performance", b"NOT ACTIVATED",
                   b"no demo balances"):
        if marker.lower() not in body.lower():
            raise AssertionError("Dashboard missing: " + marker.decode())
    status, _, body = fetch(base, "/healthz")
    if status != 200 or json.loads(body) != {"service": "up", "trading_state": "NOT_ACTIVATED"}:
        raise AssertionError("Unexpected liveness state")
    status, _, body = fetch(base, "/readyz")
    if status != 503 or json.loads(body).get("ready_for_automatic_paper_trading") is not False:
        raise AssertionError("Trading readiness must fail closed")
    # HEAD probes must not mistake liveness for trading readiness.\n    status, _, body = fetch(base, "/readyz", method="HEAD")\n    if status != 503 or body:\n        raise AssertionError("HEAD readiness must return 503 without a body")\n    status, _, body = fetch(base, "/status")
    state = json.loads(body)
    if status != 200 or any((state.get(k) is not v) for k, v in (
        ("automatic_paper_trading", False), ("real_money_trading", False)
    )) or state.get("trading_state") != "NOT_ACTIVATED":
        raise AssertionError("Trading state is not safely disabled")
    for key in ("market_data", "persistent_paper_ledger", "execution_time_risk_gate"):
        if state.get(key) != "NOT_CONNECTED":
            raise AssertionError("Unexpected integration state: " + key)
    status, _, body = fetch(base, "/version")
    actual = json.loads(body).get("git_commit")
    if status != 200 or (actual is not None and not re.fullmatch("[0-9a-f]{40}", actual)):
        raise AssertionError("Invalid deployment provenance")
    if revision is not None and actual != revision:
        raise AssertionError("Wrong deployed revision: " + str(actual))
    for path in ("/paper-account", "/paper-journal-activity"):
        status, _, body = fetch(base, path)
        data = json.loads(body)
        if status == 503:
            if data.get("available") is not False:
                raise AssertionError(path + ": invalid unavailable response")
        elif status == 200:
            if (data.get("available") is not True
                    or data.get("source") != "isolated_paper_journal"
                    or data.get("verification") != "journal_only_not_broker_or_market_verified"
                    or data.get("trading_ready") is not False):
                raise AssertionError(path + ": unverified journal response")
            if path == "/paper-account":
                money = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}\Z")
                amounts = [data.get(key) for key in ("cash", "deposits", "withdrawals")]
                if any(not isinstance(value, str) or not money.fullmatch(value)
                       or len(value) > 32 for value in amounts):
                    raise AssertionError("Invalid journal cash amounts")
                cents = [int(value.replace(".", "")) for value in amounts]
                if cents[1] - cents[2] != cents[0] or data.get("paper_trades") is not None or data.get("performance") is not None:
                    raise AssertionError("Journal cash is inconsistent or presented as trades")
            else:
                if data.get("activity_type") != "cash_movements_not_trades":
                    raise AssertionError("Journal activity mislabeled as trades")
                events = data.get("events")
                if not isinstance(events, list) or len(events) > 25:
                    raise AssertionError("Invalid journal activity collection")
                previous = 0
                for event in events:
                    if not isinstance(event, dict) or type(event.get("sequence")) is not int or event["sequence"] <= previous:
                        raise AssertionError("Invalid journal sequence")
                    previous = event["sequence"]
                    if event.get("type") not in ("paper_deposit", "paper_withdrawal"):
                        raise AssertionError("Non-cash event in journal activity")
                    amount = event.get("amount")
                    if not isinstance(amount, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.[0-9]{2}", amount):
                        raise AssertionError("Invalid journal activity amount")
        else:
            raise AssertionError(path + ": unexpected HTTP " + str(status))
    # Prove the public service rejects order-like writes; a readable dashboard
    # alone is insufficient evidence that staging cannot accept executions.
    for path in ("/orders", "/api/orders", "/paper-trade"):
        status, _, body = fetch(base, path, method="POST")
        if status != 405 or json.loads(body).get("error") != "read-only service":
            raise AssertionError(path + ": state-changing request was not rejected")
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="HTTPS origin of isolated staging service")
    parser.add_argument("--revision", help="Required 40-character lowercase deployed Git SHA")
    args = parser.parse_args()
    if args.revision and not re.fullmatch("[0-9a-f]{40}", args.revision):
        parser.error("--revision must be a lowercase 40-character Git SHA")
    try:
        actual = check(args.origin, args.revision)
    except (AssertionError, ValueError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        print("FAIL: " + str(error), file=sys.stderr)
        return 1
    print("PASS: read-only staging diagnostics; trading disabled; revision=" + str(actual))
    print("NOT a paper-trading readiness or profitability certification")
    return 0


if __name__ == "__main__":
    sys.exit(main())
