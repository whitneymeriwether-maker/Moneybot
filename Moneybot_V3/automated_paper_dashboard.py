"""Dashboard for the automated V3 paper account."""

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moneybot V3 | Paper Trading</title>
<style>
:root { color-scheme: dark; font-family: system-ui, sans-serif; background: #0d1522; color: #e6edf5; }
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 1120px; padding: 32px 18px; }
header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
h1, h2, p { margin-top: 0; }
h1 { margin-bottom: 5px; font-size: 1.7rem; }
h2 { font-size: 1.08rem; }
.muted { color: #a9bad0; }
#status { background: #293a52; border-radius: 20px; padding: 8px 14px; font-weight: 650; }
.controls { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 18px 0; }
button { border: 1px solid #496382; border-radius: 8px; padding: 8px 13px; background: #172338; color: inherit; font: inherit; cursor: pointer; }
button:disabled { opacity: .65; cursor: wait; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: 12px; }
section { background: #172338; border: 1px solid #33445d; border-radius: 12px; padding: 18px; margin-bottom: 12px; }
dl { margin: 0; font-variant-numeric: tabular-nums; }
dt { color: #a9bad0; }
dd { margin: 6px 0 0; font-size: 1.35rem; font-weight: 650; }
.positive { color: #7fe0b1; }
.negative { color: #ffa6a4; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; text-align: left; white-space: nowrap; font-variant-numeric: tabular-nums; }
td, th { padding: 9px 12px 9px 0; border-bottom: 1px solid #33445d; }
td:last-child, th:last-child { padding-right: 0; }
tbody tr:last-child td { border-bottom: 0; }
a { color: #a5ceff; }
</style>
</head>
<body>
<header><div><h1>Moneybot V3</h1><p class="muted">Isolated staging · simulated orders</p></div>
<span id="status" role="status">Checking paper trader…</span></header>
<div class="controls">
<button id="refresh" type="button">Refresh</button>
<span id="updated" class="muted" role="status">Loading account…</span>
</div>
<main id="account" hidden>
<div class="grid">
<section><dl><dt>Account value</dt><dd id="equity"></dd></dl></section>
<section><dl><dt>Cash</dt><dd id="cash"></dd></dl></section>
<section><dl><dt>Total P&amp;L</dt><dd id="total_pnl"></dd></dl></section>
<section><dl><dt>Realized P&amp;L</dt><dd id="realized_pnl"></dd></dl></section>
<section><dl><dt>Unrealized P&amp;L</dt><dd id="unrealized_pnl"></dd></dl></section>
<section><dl><dt>Total return</dt><dd id="total_return_percent"></dd></dl></section>
</div>
<section>
<h2>Holdings</h2>
<div class="table-wrap"><table><thead><tr>
<th scope="col">Symbol</th><th scope="col">Shares</th><th scope="col">Cost basis</th>
<th scope="col">Last mark</th><th scope="col">Market value</th><th scope="col">Unrealized P&amp;L</th>
</tr></thead><tbody id="positions"></tbody></table></div>
</section>
<section>
<h2>Recent simulated trades</h2>
<div class="table-wrap"><table><thead><tr>
<th scope="col">Time (ET)</th><th scope="col">Symbol</th><th scope="col">Side</th><th scope="col">Shares</th>
<th scope="col">Fill price</th><th scope="col">Amount</th><th scope="col">Realized P&amp;L</th>
</tr></thead><tbody id="trades"></tbody></table></div>
</section>
<section>
<h2>Performance history</h2>
<p id="latest-cycle" class="muted"></p>
<div class="table-wrap"><table><thead><tr>
<th scope="col">Cycle completed (ET)</th><th scope="col">Decision</th><th scope="col">Symbol</th>
<th scope="col">Market data time (ET)</th><th scope="col">Market price</th>
<th scope="col">Account value</th><th scope="col">Total P&amp;L</th>
</tr></thead><tbody id="performance"></tbody></table></div>
</section>
</main>
<footer><p><a href="/status">Service status</a> · <a href="/automated-paper">Paper account JSON</a></p></footer>
<script>
"use strict";
const byId = id => document.getElementById(id);
const currency = new Intl.NumberFormat("en-US", {style: "currency", currency: "USD"});
const time = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", dateStyle: "medium", timeStyle: "short",
});
const number = value => typeof value === "number" && Number.isFinite(value)
  || typeof value === "string" && /^-?\d+(?:\.\d+)?$/.test(value) && Number.isFinite(Number(value));
const money = value => number(value) ? currency.format(Number(value)) : "Unavailable";
const percent = value => number(value) ? Number(value).toFixed(2) + "%" : "Unavailable";
const timestamp = value => value && Number.isFinite(Date.parse(value))
  ? time.format(new Date(value)) : "Unavailable";
function color(element, value) {
  element.classList.toggle("positive", number(value) && Number(value) > 0);
  element.classList.toggle("negative", number(value) && Number(value) < 0);
}
function metric(id, value, format, signed = false) {
  const element = byId(id);
  element.textContent = format(value);
  if (signed) color(element, value);
}
function rows(id, data, columns, emptyMessage) {
  const body = byId(id);
  const fragment = document.createDocumentFragment();
  for (const entry of data) {
    const row = document.createElement("tr");
    for (const [key, format, signed] of columns) {
      const cell = row.insertCell();
      cell.textContent = format ? format(entry[key]) : (entry[key] ?? "Unavailable");
      if (signed) color(cell, entry[key]);
    }
    fragment.append(row);
  }
  if (!data.length) {
    const row = document.createElement("tr");
    const cell = row.insertCell();
    cell.colSpan = columns.length;
    cell.textContent = emptyMessage;
    fragment.append(row);
  }
  body.replaceChildren(fragment);
}
async function refresh() {
  const button = byId("refresh");
  if (button.disabled) return;
  button.disabled = true;
  try {
    const response = await fetch("/automated-paper", {cache: "no-store", signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error("Paper account unavailable");
    const data = await response.json();
    if (data.real_money_trading !== false || !number(data.cash)) throw new Error("Invalid paper account");
    const hasCycle = Boolean(data.latest_cycle);
    metric("equity", hasCycle ? data.equity : null, money);
    metric("cash", data.cash, money);
    metric("total_pnl", hasCycle ? data.total_pnl : null, money, true);
    metric("realized_pnl", hasCycle ? data.realized_pnl : null, money, true);
    metric("unrealized_pnl", hasCycle ? data.unrealized_pnl : null, money, true);
    metric("total_return_percent", hasCycle ? data.total_return_percent : null, percent, true);
    rows("positions", data.positions, [
      ["symbol"], ["shares"], ["cost_basis", money], ["last_price", money],
      ["market_value", money], ["unrealized_pnl", money, true]
    ], "No open holdings");
    rows("trades", data.trades, [
      ["executed_at", timestamp], ["symbol"], ["side"], ["shares"],
      ["price", money], ["amount", money], ["realized_pnl", money, true]
    ], "No simulated trades recorded");
    rows("performance", data.performance, [
      ["completed_at", timestamp], ["decision"], ["symbol"], ["quote_timestamp", timestamp],
      ["price", money], ["equity", money], ["total_pnl", money, true]
    ], "No completed cycles recorded");
    byId("latest-cycle").textContent = hasCycle
      ? "Latest completed cycle (ET) · " + timestamp(data.latest_cycle.completed_at)
      : "Awaiting the first completed cycle";
    let status = "Paper automation disabled";
    if (data.automatic_paper_trading) {
      status = hasCycle ? "Paper automation enabled" : "Enabled · first cycle pending";
    }
    byId("status").textContent = status;
    byId("updated").textContent = "Account refreshed (ET) · " + time.format(new Date());
    byId("account").hidden = false;
  } catch (_) {
    byId("account").hidden = true;
    byId("status").textContent = "Paper account unavailable";
    byId("updated").textContent = "Could not load the account. Retrying in 30 seconds.";
  } finally {
    button.disabled = false;
  }
}
byId("refresh").addEventListener("click", refresh);
refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>"""
