// Browser-level smoke: exercise actual dashboard JavaScript, not just HTTP or syntax.
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("http://127.0.0.1:18765/", {waitUntil: "domcontentloaded"});
    await page.waitForFunction(() => document.querySelector("#refresh-feedback")?.textContent?.includes("Refresh completed"), null, {timeout: 20000});
    const expected = {
      "#service-health": "Service reachable · trading disabled",
      "#readiness-health": "Paper execution NOT READY",
      "#integration-health": "integrations NOT CONNECTED",
      "#paper-account-state": "unavailable",
      "#ledger-summary": "unavailable",
      "#offline-realized-pnl": "Unavailable",
    };
    for (const [selector, value] of Object.entries(expected)) {
      const actual = await page.locator(selector).innerText();
      if (!actual.toLowerCase().includes(value.toLowerCase()))
        throw new Error(selector + " unexpected: " + actual);
    }
    if (await page.locator("#hypothetical-fill-rows tr").count())
      throw new Error("Unverified fills rendered");
    if (await page.locator("#hypothetical-position-rows tr").count())
      throw new Error("Unverified positions rendered");
    // Require a NEW successful health request after the user click; a stale label is insufficient.
    const refreshedHealth = page.waitForResponse(response =>
      new URL(response.url()).pathname === "/healthz" && response.status() === 200,
      {timeout: 20000});
    await page.locator("#refresh-now").click();
    await refreshedHealth;
    // A stale "Refresh completed" label must not satisfy this second-cycle test.
    await page.waitForFunction(() => {
      const button = document.querySelector("#refresh-now");
      const feedback = document.querySelector("#refresh-feedback");
      return !button?.disabled && feedback?.textContent?.includes("Refresh completed");
    }, null, {timeout: 20000});
    if (errors.length) throw new Error("Browser JS errors: " + errors.join("; "));
    console.log("PASS: actual Chromium dashboard render, refresh, fail-closed labels and empty unverified tables");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
