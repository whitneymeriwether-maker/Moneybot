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
    // Adversarial browser check: a plausible ledger summary must never survive
    // a failed transaction-history read as an "audited" P&L or fill count.
    let summaryIntercepts = 0;
    let failedFillIntercepts = 0;
    await page.route("**/paper-ledger-summary", route => { summaryIntercepts++; return route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        available: true, source: "local_hypothetical_sqlite_ledger",
        verification: "audited_local_records_not_broker_verified",
        trading_ready: false, fill_count: 1, position_count: 1,
        cash: "1000.00", realized_pnl: "250.00",
        marked_equity: null, performance: null
      })
    }); });
    let positionIntercepts = 0;
    await page.route("**/paper-ledger-positions", route => { positionIntercepts++; return route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({available: true, source: "local_hypothetical_sqlite_ledger",
        verification: "audited_local_records_not_broker_verified", trading_ready: false,
        market_valued: false, fill_count: 1,
        positions: [{symbol: "TEST", quantity: 2, cost_basis: "100.00"}]})
    }); });
    await page.route("**/paper-ledger-fills", route => { failedFillIntercepts++; return route.fulfill({
      status: 503, contentType: "application/json",
      body: JSON.stringify({available: false})
    }); });
    await page.locator("#refresh-now").click();
    await page.waitForFunction(() => !document.querySelector("#refresh-now")?.disabled, null, {timeout: 20000});
    if (summaryIntercepts !== 1 || positionIntercepts !== 1 || failedFillIntercepts !== 1)
      throw new Error(`Adversarial requests not exercised: summary=${summaryIntercepts}, positions=${positionIntercepts}, fills=${failedFillIntercepts}`);
    const rejectedPnl = await page.locator("#offline-realized-pnl").innerText();
    const rejectedSummary = await page.locator("#ledger-summary").innerText();
    if (!rejectedPnl.includes("Unavailable") || !rejectedSummary.includes("inconsistent"))
      throw new Error("Contradictory ledger responses were not rejected: " + rejectedPnl + " / " + rejectedSummary);
    if (await page.locator("#hypothetical-fill-rows tr").count())
      throw new Error("Failed ledger read left hypothetical fills visible");
    if (await page.locator("#hypothetical-position-rows tr").count())
      throw new Error("Failed fill audit left hypothetical positions visible");
    // A valid-looking fill feed must not make a contradictory position count acceptable.
    await page.unroute("**/paper-ledger-summary");
    await page.route("**/paper-ledger-summary", route => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({available: true, source: "local_hypothetical_sqlite_ledger",
        verification: "audited_local_records_not_broker_verified", trading_ready: false,
        fill_count: 1, position_count: 2, cash: "1000.00", realized_pnl: "0.00",
        marked_equity: null, performance: null})
    }));
    await page.unroute("**/paper-ledger-fills");
    await page.route("**/paper-ledger-fills", route => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({available: true, source: "local_hypothetical_sqlite_ledger",
        verification: "audited_local_records_not_broker_verified", trading_ready: false,
        fill_count: 1, fills: [{timestamp_utc: "2026-11-20T12:00:00+00:00",
          symbol: "TEST", side: "BUY", quantity: 2, price: "50.00", fee: "0.00"}]})
    }));
    await page.locator("#refresh-now").click();
    await page.waitForFunction(() => !document.querySelector("#refresh-now")?.disabled, null, {timeout: 20000});
    if (await page.locator("#hypothetical-position-rows tr").count())
      throw new Error("Inconsistent position count rendered purported audited holdings");
    if (!(await page.locator("#hypothetical-position-status").innerText()).includes("unavailable"))
      throw new Error("Inconsistent position count not marked unverified");
    if (errors.length) throw new Error("Browser JS errors: " + errors.join("; "));
    console.log("PASS: actual Chromium dashboard render, refresh, fail-closed labels and empty unverified tables");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
