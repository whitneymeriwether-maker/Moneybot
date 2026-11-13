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
    if (errors.length) throw new Error("browser JS errors: " + errors.join("; "));
    console.log("PASS: real Chromium rendered isolated V3 staging dashboard, revision " + revision);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
