"""Exercise the actual V3 dashboard JavaScript in a headless browser.

This is an HTTP/browser smoke test only; it never enables paper or live orders.
"""
import os
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from pathlib import Path
# Executed as tests/browser_smoke.py from the Moneybot_V3 working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_journal import PaperJournal
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

PORT = "18944"
# Exercise a real persisted, isolated journal through the HTTP server and JS.
# Browser route mocks below remain separate adversarial-response tests.
journal_dir = TemporaryDirectory(prefix="moneybot-v3-browser-")
journal_path = Path(journal_dir.name) / "paper-only.sqlite3"
journal = PaperJournal(journal_path)
assert journal.record("browser-seed", "paper_deposit", "1000.25", {})
assert journal.record("browser-withdrawal", "paper_withdrawal", "75.10", {})
test_revision = "a" * 40  # Deterministic provenance for local CI, not a deployed SHA.
env = dict(os.environ, PORT=PORT, RENDER_GIT_COMMIT=test_revision, MONEYBOT_V3_ACTIVATION="false",
           MONEYBOT_V3_PAPER_JOURNAL_PATH=str(journal_path))
process = subprocess.Popen([sys.executable, "paper_status_server.py"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError("staging server exited before browser test")
        try:
            with urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=1) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        raise RuntimeError("staging server did not become healthy")
    # Exercise the deployed HTTP boundary, not just dashboard labels: a
    # healthy read-only service must reject every order-like mutation.
    from urllib.error import HTTPError
    from urllib.request import Request
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        request = Request(f"http://127.0.0.1:{PORT}/orders",
                          data=b'{"symbol":"TEST","quantity":1}', method=method)
        try:
            urlopen(request, timeout=2)
            raise AssertionError(f"{method} unexpectedly accepted")
        except HTTPError as error:
            assert error.code == 405, (method, error.code)
    try:
        urlopen(Request(f"http://127.0.0.1:{PORT}/readyz", method="HEAD"), timeout=2)
        raise AssertionError("HEAD readiness unexpectedly succeeded")
    except HTTPError as error:
        assert error.code == 503
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
        page.locator("#service-health").get_by_text("Service reachable · trading disabled").wait_for()
        page.locator("#readiness-health").get_by_text("Paper execution NOT READY").wait_for()
        page.locator("#integration-health").get_by_text("integrations NOT CONNECTED").wait_for()
        page.locator("#paper-account-state").get_by_text(
            "Journal-only cash: 925.15 · NOT broker verified").wait_for()
        page.locator("#journal-activity-status").get_by_text(
            "Journal-only cash movements · NOT verified paper trades").wait_for()
        assert page.locator("#journal-activity-rows tr").count() == 2
        page.locator("#deployed-revision").get_by_text("Deployed Git revision: " + test_revision).wait_for()
        assert page.get_by_text("Actual state only").count() == 1
        for heading in ("System health", "Account state", "Paper trades",
                        "Risk limits", "Performance", "Integration status"):
            assert page.get_by_role("heading", name=heading).count() == 1
        assert page.get_by_text("No verified realized P&L", exact=False).count() == 1
        # A compromised or misconfigured upstream must not appear trade-ready.
        # Browser assertions exercise the actual JavaScript fail-closed branch.
        page.route("**/readyz", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"ready_for_automatic_paper_trading":true}'))
        page.route("**/paper-account", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"available":true,"source":"demo","cash":"999999"}'))
        page.reload(wait_until="domcontentloaded")
        page.locator("#readiness-health").get_by_text(
            "Unexpected readiness response · trading unverified").wait_for()
        page.locator("#paper-account-state").get_by_text(
            "Paper account unverified").wait_for()
        assert page.get_by_text("Journal-only cash:", exact=False).count() == 0
        # A source label alone is insufficient: malformed monetary values
        # must never be displayed as actual journal cash.
        page.route("**/paper-account", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"available":true,"source":"isolated_paper_journal",'
                 '"verification":"journal_only_not_broker_or_market_verified",'
                 '"trading_ready":false,"cash":"NaN","deposits":"1250.00",'
                 '"withdrawals":"50.00","event_count":2,'
                 '"paper_trades":null,"performance":null}'))
        page.reload(wait_until="domcontentloaded")
        page.locator("#paper-account-state").get_by_text("Paper account unverified").wait_for()
        assert page.get_by_text("Journal-only cash:", exact=False).count() == 0
        # A plausible but internally inconsistent journal must not be shown.
        page.route("**/paper-account", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"available":true,"source":"isolated_paper_journal",'
                 '"verification":"journal_only_not_broker_or_market_verified",'
                 '"trading_ready":false,"cash":"1201.00","deposits":"1250.00",'
                 '"withdrawals":"50.00","event_count":2,'
                 '"paper_trades":null,"performance":null}'))
        page.reload(wait_until="domcontentloaded")
        page.locator("#paper-account-state").get_by_text("Paper account unverified").wait_for()
        assert page.get_by_text("Journal-only cash:", exact=False).count() == 0
        # Even a healthy liveness probe must not override a contradictory
        # integration snapshot. No "connected" or ready state may leak through.
        page.route("**/status", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"application":"Moneybot V3","trading_state":"ACTIVE",'
                 '"automatic_paper_trading":true,"real_money_trading":false,'
                 '"market_data":"CONNECTED","persistent_paper_ledger":"CONNECTED",'
                 '"execution_time_risk_gate":"CONNECTED"}'))
        page.reload(wait_until="domcontentloaded")
        page.locator("#service-health").get_by_text(
            "Service reachable · trading disabled").wait_for()
        page.locator("#integration-health").get_by_text(
            "Unexpected status response · integrations unverified").wait_for()
        page.locator("#readiness-health").get_by_text(
            "Unexpected readiness response · trading unverified").wait_for()
        # Positive path: a valid, explicitly journal-only cash snapshot must
        # render without being mislabeled as broker equity or verified fills.
        page.unroute_all()
        page.route("**/paper-account", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"available":true,"source":"isolated_paper_journal",'
                 '"verification":"journal_only_not_broker_or_market_verified",'
                 '"trading_ready":false,"cash":"1200.00","deposits":"1250.00",'
                 '"withdrawals":"50.00","event_count":2,'
                 '"last_recorded_at":"2026-11-10T01:00:00+00:00",'
                 '"paper_trades":null,"performance":null}'))
        page.route("**/paper-journal-activity", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"available":true,"source":"isolated_paper_journal",'
                 '"verification":"journal_only_not_broker_or_market_verified",'
                 '"activity_type":"cash_movements_not_trades","trading_ready":false,'
                 '"events":[{"sequence":1,"type":"paper_deposit","amount":"1250.00",'
                 '"recorded_at":"2026-11-10T00:00:00+00:00"},'
                 '{"sequence":2,"type":"paper_withdrawal","amount":"50.00",'
                 '"recorded_at":"2026-11-10T01:00:00+00:00"}]}'))
        page.reload(wait_until="domcontentloaded")
        page.locator("#paper-account-state").get_by_text(
            "Journal-only cash: 1200.00 · NOT broker verified").wait_for()
        page.locator("#journal-activity-status").get_by_text(
            "Journal-only cash movements · NOT verified paper trades").wait_for()
        assert page.locator("#journal-activity-rows tr").count() == 2
        assert page.get_by_text("No verified realized P&L", exact=False).count() == 1
        # Invalid activity must remove previously displayed rows on refresh.
        page.unroute("**/paper-journal-activity")
        page.route("**/paper-journal-activity", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"available":true,"source":"isolated_paper_journal",'
                 '"verification":"journal_only_not_broker_or_market_verified",'
                 '"activity_type":"cash_movements_not_trades","trading_ready":false,'
                 '"events":[{"sequence":1,"type":"paper_fill","amount":"999.00",'
                 '"recorded_at":"2026-11-10T01:00:00+00:00"}]}'))
        page.reload(wait_until="domcontentloaded")
        page.locator("#journal-activity-status").get_by_text(
            "Cash activity unavailable or unverified").wait_for()
        assert page.locator("#journal-activity-rows tr").count() == 0
        browser.close()
    print("Headless browser smoke passed: real JS fetches and fail-closed labels")
finally:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    journal_dir.cleanup()
