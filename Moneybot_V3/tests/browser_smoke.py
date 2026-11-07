"""Exercise the actual V3 dashboard JavaScript in a headless browser.

This is an HTTP/browser smoke test only; it never enables paper or live orders.
"""
import os
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

PORT = "18944"
env = dict(os.environ, PORT=PORT, MONEYBOT_V3_ACTIVATION="false")
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
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
        page.locator("#service-health").get_by_text("Service reachable · trading disabled").wait_for()
        page.locator("#readiness-health").get_by_text("Paper execution NOT READY").wait_for()
        page.locator("#integration-health").get_by_text("integrations NOT CONNECTED").wait_for()
        page.locator("#paper-account-state").get_by_text("Paper account unavailable").wait_for()
        page.locator("#deployed-revision").get_by_text("Deployment revision unavailable").wait_for()
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
        page.reload(wait_until="networkidle")
        page.locator("#readiness-health").get_by_text(
            "Unexpected readiness response · trading unverified").wait_for()
        page.locator("#paper-account-state").get_by_text(
            "Paper account unverified").wait_for()
        assert page.get_by_text("Journal-only cash:", exact=False).count() == 0
        browser.close()
    print("Headless browser smoke passed: real JS fetches and fail-closed labels")
finally:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
