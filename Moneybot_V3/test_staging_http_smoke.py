"""Local HTTP contract smoke tests for the isolated, read-only V3 dashboard."""
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from paper_status_server import StatusHandler


@pytest.fixture
def staging_server(monkeypatch):
    monkeypatch.delenv("MONEYBOT_V3_PAPER_JOURNAL_PATH", raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), StatusHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()


def request(port, method, path):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def test_dashboard_served_with_explicit_unavailable_states(staging_server):
    status, headers, body = request(staging_server, "GET", "/")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    for label in (b"System health", b"Account state", b"Paper trades",
                  b"Risk limits", b"Performance", b"NOT ACTIVATED",
                  b"no demo balances"):
        assert label.lower() in body.lower()


def test_liveness_does_not_imply_trading_readiness(staging_server):
    status, _, body = request(staging_server, "GET", "/healthz")
    assert status == 200
    assert json.loads(body)["trading_state"] == "NOT_ACTIVATED"
    status, _, body = request(staging_server, "GET", "/readyz")
    assert status == 503
    assert json.loads(body)["ready_for_automatic_paper_trading"] is False
    status, _, body = request(staging_server, "HEAD", "/readyz")
    assert status == 503 and body == b""


def test_missing_ledger_fails_closed_without_fabricated_data(staging_server):
    for endpoint in ("/paper-account", "/paper-journal-activity"):
        status, _, body = request(staging_server, "GET", endpoint)
        assert status == 503
        assert json.loads(body)["available"] is False


def test_all_mutating_methods_rejected(staging_server):
    for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        status, _, body = request(staging_server, method, "/orders")
        assert status == 405
        assert json.loads(body)["error"] == "read-only service"


def test_status_discloses_disabled_integrations(staging_server):
    status, _, body = request(staging_server, "GET", "/status")
    assert status == 200
    data = json.loads(body)
    assert data["automatic_paper_trading"] is False
    assert data["real_money_trading"] is False
    assert data["market_data"] == "NOT_CONNECTED"
    assert data["execution_time_risk_gate"] == "NOT_CONNECTED"
