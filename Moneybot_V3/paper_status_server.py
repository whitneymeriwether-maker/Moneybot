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
<html lang="en"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width, initial-scale=1">
<title>Moneybot V3 — staging</title>
<style>body{font:16px/1.6 system-ui,sans-serif;max-width:700px;margin:7vh auto;
padding:0 20px;color:#202833;background:#f8fafc}main{background:white;
padding:32px;border:1px solid #e0e6ed;border-radius:12px}
h1{margin-top:0}strong{color:#92400e}code{background:#f1f5f9;
padding:2px 5px;border-radius:4px}</style></head>
<body><main><h1>Moneybot V3</h1>
<p><strong>NOT ACTIVATED — staging only</strong></p>
<p>This page confirms the separate V3 web service is reachable. It is not
automatic paper trading, does not generate signals, and does not report
trading performance.</p>
<p>Market data, persistent paper ledger, and execution-time risk controls
must be connected and validated before activation.</p>
<p>Diagnostic endpoints: <code>/healthz</code>, <code>/status</code>,
<code>/readyz</code>.</p>
<p>No live-money or paper orders can be submitted by this service.</p>
</main></body></html>"""


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
        self.wfile.write(payload)

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
