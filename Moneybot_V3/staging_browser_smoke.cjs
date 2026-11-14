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
    if (errors.length) throw new Error("browser JS errors: " + errors.join("; "));
    console.log("PASS: real Chromium rendered isolated V3 staging dashboard, revision " + revision);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
