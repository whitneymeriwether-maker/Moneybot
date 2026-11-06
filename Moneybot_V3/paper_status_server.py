"""Moneybot V3 staging status endpoint; deliberately incapable of trading.

This service is a deployment smoke-test, not a paper trading engine. It
has no broker, market-data, persistence, background worker, or order path.
It stays disabled even if an activation-looking environment variable is set.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


_STATUS = {
    "application": "Moneybot V3",
    "environment": "isolated staging",
    "mode": "research-and-paper-only",
    "trading_state": "NOT_ACTIVATED",
    "automatic_paper_trading": False,
    "real_money_trading": False,
    "market_data": "NOT_CONNECTED",
    "persistent_paper_ledger": "NOT_CONNECTED",
    "execution_time_risk_gate": "NOT_CONNECTED",
    "note": "Deployment smoke-test only. No trades, signals, or performance data.",
}

_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moneybot V3 | Paper Research Dashboard</title>
<style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#e6edf5;background:#0d1522}
*{box-sizing:border-box}body{max-width:1120px;margin:auto;padding:30px 18px}
header{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
h1{margin:0;font-size:1.7rem}h2{font-size:1rem;margin:0 0 14px}p{line-height:1.5}
.tag{background:#382f17;color:#ffdb87;padding:8px 12px;border-radius:20px;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;margin-top:22px}
section{background:#172338;border:1px solid #33445d;border-radius:12px;padding:20px}
.value{font-size:1.25rem;font-weight:700}.muted{color:#a9bad0}.warn{color:#ffdb87}
table{width:100%;border-collapse:collapse;text-align:left}td,th{padding:10px 4px;border-bottom:1px solid #33445d}
.full{grid-column:1/-1}code{color:#c8d9f2}a{color:#a5ceff}
</style></head><body>
<header><div><h1>Moneybot V3</h1><p class="muted">Isolated staging · research &amp; paper-only</p></div>
<span class="tag">NOT ACTIVATED</span></header>
<p class="warn"><strong>Actual state only — no demo balances, fabricated trades, or simulated performance are shown.</strong>
This dashboard is a read-only staging diagnostic, not an operating paper trader.</p>
<div class="grid">
<section><h2>System health</h2><div class="value">Service reachable</div><p class="muted">HTTP liveness only; trading readiness is unavailable.</p><p><a href="/healthz">Liveness JSON</a> · <a href="/readyz">Readiness JSON</a></p></section>
<section><h2>Account state</h2><div class="value">Not connected</div><p class="muted">Actual paper cash, equity, buying power, and positions: unavailable. No demo values.</p></section>
<section><h2>Paper trades</h2><div class="value">Not connected</div><p class="muted">No verified trade feed or persisted paper execution attached to this service. Trade count unknown, not zero.</p></section>
<section><h2>Risk limits</h2><div class="value warn">Execution gate unavailable</div><p class="muted">Research policy targets (not enforced here): 1.5% risk/trade, 3% daily loss, 50% exposure, 10% drawdown pause, 25% overnight exposure.</p></section>
<section><h2>Performance</h2><div class="value">Unavailable</div><p class="muted">No verified realized P&amp;L, return, drawdown, or equity curve. No profitability claim.</p></section>
<section><h2>Integration status</h2><table><tr><th>Component</th><th>Actual state</th></tr>
<tr><td>Market data</td><td>Not connected</td></tr><tr><td>Durable paper ledger</td><td>Not connected</td></tr>
<tr><td>Automatic paper execution</td><td>Disabled</td></tr><tr><td>Live orders</td><td>Disabled</td></tr></table></section>
<section class="full"><h2>Operational status</h2><p>Trading readiness: <strong class="warn">NOT READY</strong>.
No live-money or paper orders can be submitted by this service. Check <a href="/status">machine-readable status</a>.
This page deliberately does not equate a green health check with trading readiness.</p></section>
</div></body></html>"""


class StatusHandler(BaseHTTPRequestHandler):
    """Read-only HTTP handler with a permanently closed trading gate."""

    def _send(self, status, body, content_type):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(payload)

    def do_HEAD(self):
        """Expose the same status as GET without a response body.

        Render and other uptime probes may issue HEAD before GET. A HEAD
        request must not make the staging service appear unhealthy, and
        /readyz must remain 503 even when probed with HEAD.
        """
        self._head_only = True
        try:
            self.do_GET()
        finally:
            # HEAD must not suppress a subsequent GET on a reused connection.
            self._head_only = False

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, _HTML, "text/html; charset=utf-8")
        elif path == "/healthz":
            self._send(
                200,
                json.dumps({"service": "up", "trading_state": "NOT_ACTIVATED"}),
                "application/json; charset=utf-8",
            )
        elif path == "/status":
            self._send(200, json.dumps(_STATUS), "application/json; charset=utf-8")
        elif path == "/readyz":
            self._send(
                503,
                json.dumps({
                    "ready_for_automatic_paper_trading": False,
                    "reason": "Required integrations and safeguards unvalidated",
                }),
                "application/json; charset=utf-8",
            )
        else:
            self._send(404, '{"error":"not found"}', "application/json; charset=utf-8")

    def do_POST(self):
        self._send(405, '{"error":"read-only service"}', "application/json; charset=utf-8")

    # Explicitly reject every state-changing HTTP method with the same
    # fail-closed response, including on order-like paths.
    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    # Do not advertise alternate methods or expose request reflection.
    do_OPTIONS = do_POST
    do_TRACE = do_POST
    do_CONNECT = do_POST


def main():
    raw_port = os.environ.get("PORT", "10000")
    if not raw_port.isascii() or not raw_port.isdecimal():
        raise ValueError("Invalid PORT")
    port = int(raw_port)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid PORT")
    server = ThreadingHTTPServer(("0.0.0.0", port), StatusHandler)
    print("Moneybot V3 staging status service; trading NOT ACTIVATED", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
