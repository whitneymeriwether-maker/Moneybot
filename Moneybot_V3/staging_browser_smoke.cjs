"use strict";
const { chromium } = require("playwright");

(async () => {
  const origin = "https://moneybot-v3-staging.onrender.com";
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const response = await page.goto(origin, { waitUntil: "domcontentloaded", timeout: 90000 });
    if (!response || response.status() !== 200 || new URL(page.url()).origin !== origin)
      throw new Error("staging browser navigation failed or redirected");
    await page.locator("#service-health").getByText("Service reachable · trading disabled").waitFor({ timeout: 30000 });
    await page.locator("#integration-health").getByText("Verified snapshot: integrations NOT CONNECTED · trading disabled").waitFor({ timeout: 30000 });
    await page.locator("#readiness-health").getByText(/NOT READY|not ready/i).waitFor({ timeout: 30000 });
    const revision = await page.locator("#deployed-revision").innerText();
    if (!/Deployed Git revision: [a-f0-9]{40}/.test(revision))
      throw new Error("browser did not verify deployment provenance");
    for (const title of ["System health", "Account state", "Paper trades", "Risk limits", "Performance", "Integration status"]) {
      if (await page.getByRole("heading", { name: title, exact: true }).count() !== 1)
        throw new Error("missing dashboard section: " + title);
    }
    const body = await page.locator("body").innerText();
    if (!body.includes("Actual state only") || !body.includes("NOT ACTIVATED") ||
        !body.includes("hypothetical") || !body.includes("NOT broker verified") ||
        !body.includes("Execution gate unavailable"))
      throw new Error("missing actual-vs-demo or risk disclosure");
    // Verify the rendered account and performance panels fail closed when the
    // isolated staging ledger is unavailable; section headings alone are insufficient.
    for (const [selector, expected] of [
      ["#paper-account-state", /unavailable/i],
      ["#ledger-summary", /unavailable/i],
      ["#offline-realized-pnl", /unavailable/i],
      ["#hypothetical-fill-status", /unavailable/i]
    ]) {
      const value = await page.locator(selector).innerText();
      if (!expected.test(value))
        throw new Error("unverified or fabricated dashboard data at " + selector + ": " + value);
    }
    if (await page.locator("#hypothetical-fill-rows").locator("tr").count() !== 0)
      throw new Error("staging rendered paper fills without a verified ledger");
    // Probe the deployed HTTP boundary, not just visible labels. A dashboard
    // must never expose an accidental order or state-changing endpoint.
    for (const endpoint of ["/", "/status", "/paper-account", "/orders", "/trade", "/execute"]) {
      const result = await page.request.post(origin + endpoint, {
        data: { symbol: "SPY", side: "BUY", quantity: 1 },
        maxRedirects: 0,
        timeout: 30000
      });
      if (result.status() < 400)
        throw new Error("unsafe POST accepted at " + endpoint + ": " + result.status());
    }
    const ready = await page.request.get(origin + "/readyz", { maxRedirects: 0 });
    if (ready.status() !== 503 ||
        (await ready.json()).ready_for_automatic_paper_trading !== false)
      throw new Error("deployed execution readiness must fail closed");
    const status = await page.request.get(origin + "/status", { maxRedirects: 0 });
    if (status.status() !== 200) throw new Error("status endpoint unavailable");
    const snapshot = await status.json();
    if (snapshot.real_money_trading !== false || snapshot.automatic_paper_trading !== false ||
        snapshot.trading_state !== "NOT_ACTIVATED")
      throw new Error("deployed trading state is not disabled");
    // Inject internally inconsistent ledger endpoints into a separate browser view.
    // The UI must reject hypothetical fills even when both endpoints individually
    // claim to be audited. This does not mutate the deployed service.
    const adversarial = await browser.newPage();
    try {
      await adversarial.route("**/paper-ledger-summary", route => route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          available: true, source: "local_hypothetical_sqlite_ledger",
          verification: "audited_local_records_not_broker_verified",
          trading_ready: false, fill_count: 2, position_count: 0,
          cash: "1000.00", realized_pnl: "0.00",
          marked_equity: null, performance: null
        })
      }));
      await adversarial.route("**/paper-ledger-fills", route => route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          available: true, source: "local_hypothetical_sqlite_ledger",
          verification: "audited_local_records_not_broker_verified",
          trading_ready: false, fill_count: 1,
          fills: [{timestamp_utc:"2026-11-14T00:00:00+00:00",
            symbol:"SPY",side:"BUY",quantity:1,price:"100.00",fee:"0.00"}]
        })
      }));
      await adversarial.goto(origin, {waitUntil:"domcontentloaded", timeout:90000});
      // Wait for the final fail-closed state, not a transient optimistic render.
      // A fast UI may reconcile both responses before any intermediate count is visible.
      await adversarial.locator("#hypothetical-fill-status").getByText(/unavailable or unverified/i).waitFor();
      await adversarial.locator("#ledger-summary").getByText(/unavailable or inconsistent/i).waitFor();
      await adversarial.locator("#offline-realized-pnl").getByText(/unavailable.*inconsistent/i).waitFor();
      if (await adversarial.locator("#hypothetical-fill-rows tr").count())
        throw new Error("dashboard displayed contradictory hypothetical fills");
    } finally {
      await adversarial.close();
    }
    if (errors.length) throw new Error("browser JS errors: " + errors.join("; "));
    console.log("PASS: real Chromium rendered isolated V3 staging dashboard, revision " + revision);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
