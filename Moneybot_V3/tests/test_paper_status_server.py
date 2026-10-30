"""Staging status server must never imply trading readiness or accept orders."""

import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from paper_status_server import StatusHandler


@contextmanager
def staging_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def get_response(url, method="GET"):
    request = Request(url, method=method)
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, response.headers, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, error.headers, error.read().decode("utf-8")


def test_status_reports_unactivated_and_no_integrations(monkeypatch):
    monkeypatch.setenv("MONEYBOT_V3_ACTIVATION", "true")
    monkeypatch.setenv("APCA_API_KEY_ID", "private-sentinel")
    monkeypatch.setenv("DATABASE_URL", "private-database-sentinel")
    with staging_server() as url:
        status, headers, body = get_response(url + "/status")
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    data = json.loads(body)
    assert data["trading_state"] == "NOT_ACTIVATED"
    assert data["automatic_paper_trading"] is False
    assert data["real_money_trading"] is False
    assert data["market_data"] == "NOT_CONNECTED"
    assert data["persistent_paper_ledger"] == "NOT_CONNECTED"
    assert "private-sentinel" not in body
    assert "private-database-sentinel" not in body


def test_liveness_is_not_trading_readiness():
    with staging_server() as url:
        live, _, live_body = get_response(url + "/healthz")
        ready, _, ready_body = get_response(url + "/readyz")
    assert live == 200
    assert json.loads(live_body)["trading_state"] == "NOT_ACTIVATED"
    assert ready == 503
    assert json.loads(ready_body)["ready_for_automatic_paper_trading"] is False


def test_home_page_explicitly_disclaims_performance():
    with staging_server() as url:
        code, headers, body = get_response(url)
    assert code == 200
    assert headers.get_content_type() == "text/html"
    assert "NOT ACTIVATED" in body
    assert "does not report" in body
    assert "No live-money or paper orders" in body


def test_order_like_post_is_rejected():
    with staging_server() as url:
        code, _, body = get_response(url + "/orders", method="POST")
    assert code == 405
    assert json.loads(body)["error"] == "read-only service"


def test_unknown_route_is_not_a_trading_endpoint():
    with staging_server() as url:
        code, _, body = get_response(url + "/api/broker/orders")
    assert code == 404
    assert json.loads(body)["error"] == "not found"
