"""Browser-level journal projection test; no trades, orders, or broker access."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright
from paper_journal import PaperJournal

with tempfile.TemporaryDirectory() as directory:
    journal_path = str(Path(directory) / "isolated-paper.sqlite3")
    journal = PaperJournal(journal_path)
    assert journal.record("seed-1", "paper_deposit", "1250.00", {})
    assert journal.record("withdraw-1", "paper_withdrawal", "50.00", {})
    env = dict(os.environ, PORT="18945", MONEYBOT_V3_ACTIVATION="false",
               MONEYBOT_V3_PAPER_JOURNAL_PATH=journal_path)
    process = subprocess.Popen([sys.executable, "paper_status_server.py"],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if process.poll() is not None:
                raise RuntimeError("V3 server exited")
            try:
                with urlopen("http://127.0.0.1:18945/healthz", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("V3 server failed to start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("http://127.0.0.1:18945/", wait_until="networkidle")
            page.locator("#paper-account-state").get_by_text(
                "Journal-only cash: 1200.00 · NOT broker verified").wait_for()
            page.locator("#paper-account-movements").get_by_text(
                "Journal-only deposits: 1250.00 · withdrawals: 50.00 · recorded events: 2").wait_for()
            page.locator("#readiness-health").get_by_text("Paper execution NOT READY").wait_for()
            # An unverified fill observation must invalidate the entire cash projection.
            journal.record("unverified-fill", "paper_fill_observation", "10.00", {})
            page.reload(wait_until="networkidle")
            page.locator("#paper-account-state").get_by_text(
                "Paper account unavailable · no verified balance").wait_for()
            assert page.get_by_text("Journal-only cash:", exact=False).count() == 0
            page.locator("#readiness-health").get_by_text("Paper execution NOT READY").wait_for()
            browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
print("Browser journal smoke passed: real journal labels and fail-closed invalidation")
