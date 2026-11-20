// Browser-level smoke: exercise actual dashboard JavaScript, not just HTTP or syntax.
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("http://127.0.0.1:18765/", {waitUntil: "domcontentloaded"});
    await page.locator("#refresh-feedback").getByText("Refresh completed", {exact: false}).waitFor({timeout: 20000});
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
    await page.locator("#refresh-now").click();
    await page.locator("#refresh-feedback").getByText("Refresh completed", {exact: false}).waitFor({timeout: 20000});
    if (await page.locator("#refresh-now").isDisabled())
      throw new Error("Refresh button remained disabled");
    if (errors.length) throw new Error("Browser JS errors: " + errors.join("; "));
    console.log("PASS: actual Chromium dashboard render, refresh, fail-closed labels and empty unverified tables");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
