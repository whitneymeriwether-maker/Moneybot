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
    assert "No verified realized P&amp;L" in body
    assert "No live-money or paper orders" in body


def test_order_like_post_is_rejected():
    with staging_server() as url:
        code, _, body = get_response(url + "/orders", method="POST")
    assert code == 405
    assert json.loads(body)["error"] == "read-only service"


def test_all_mutating_methods_fail_closed_on_order_path():
    with staging_server() as url:
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"):
            code, headers, body = get_response(url + "/api/broker/orders", method=method)
            assert code == 405, method
            assert headers["Cache-Control"] == "no-store"
            assert headers["X-Content-Type-Options"] == "nosniff"
            assert json.loads(body) == {"error": "read-only service"}


def test_unknown_route_is_not_a_trading_endpoint():
    with staging_server() as url:
        code, _, body = get_response(url + "/api/broker/orders")
    assert code == 404
    assert json.loads(body)["error"] == "not found"


def test_head_then_get_on_reused_http_connection():
    """A HEAD request must not suppress the next GET response body."""
    import http.client

    class KeepAliveStatusHandler(StatusHandler):
        protocol_version = "HTTP/1.1"

    server = ThreadingHTTPServer(("127.0.0.1", 0), KeepAliveStatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
    try:
        connection.request("HEAD", "/readyz")
        head = connection.getresponse()
        assert head.status == 503
        assert head.read() == b""
        connection.request("GET", "/status")
        response = connection.getresponse()
        assert response.status == 200
        payload = response.read()
        assert json.loads(payload)["trading_state"] == "NOT_ACTIVATED"
        assert len(payload) == int(response.getheader("Content-Length"))
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_dashboard_is_explicit_about_missing_actual_data_and_risk():
    with staging_server() as url:
        code, headers, body = get_response(url + "/")
    assert code == 200
    assert headers["Cache-Control"] == "no-store"
    for section in ("System health", "Account state", "Paper trades",
                    "Risk limits", "Performance", "Integration status"):
        assert section in body
    assert "Trade count unknown, not zero" in body
    assert "No demo values" in body
    assert "Execution gate unavailable" in body
    assert "No profitability claim" in body
    assert "NOT READY" in body
    assert 'href="/status"' in body
    assert 'href="/readyz"' in body


def test_dashboard_health_indicator_is_live_and_fail_closed():
    with staging_server() as url:
        code, _, body = get_response(url + "/")
    assert code == 200
    assert 'id="service-health"' in body
    assert 'aria-live="polite"' in body
    assert 'fetch("/healthz", {cache: "no-store"})' in body
    assert 'data.trading_state === "NOT_ACTIVATED"' in body
    assert "Service health unavailable · trading unverified" in body
    assert "setInterval(refreshHealth, 30000)" in body
    assert 'id="readiness-health"' in body
    assert 'fetch("/readyz", {cache: "no-store"})' in body
    assert "response.status === 503" in body
    assert "data.ready_for_automatic_paper_trading === false" in body
    assert "Unexpected readiness response · trading unverified" in body
    assert "Trading readiness unavailable · trading unverified" in body
    assert "innerHTML" not in body


def test_dashboard_integration_poll_is_independent_and_fail_closed():
    with staging_server() as url:
        code, _, body = get_response(url + "/")
    assert code == 200
    assert 'id="integration-health"' in body
    assert 'fetch("/status", {cache: "no-store"})' in body
    for field in ("market_data", "persistent_paper_ledger", "execution_time_risk_gate",
                  "automatic_paper_trading", "real_money_trading"):
        assert "data." + field in body
    assert "Unexpected status response · integrations unverified" in body
    assert "Integration status unavailable · trading unverified" in body
    assert "Verified snapshot: integrations NOT CONNECTED" in body
    assert "innerHTML" not in body


def test_paper_account_fails_closed_without_config(monkeypatch):
    monkeypatch.delenv("MONEYBOT_V3_PAPER_JOURNAL_PATH", raising=False)
    with staging_server() as url:
        code, _, body = get_response(url + "/paper-account")
    assert code == 503
    assert json.loads(body)["available"] is False


def test_paper_account_fails_closed_for_missing_or_corrupt_journal(monkeypatch, tmp_path):
    journal = tmp_path / "missing.db"
    monkeypatch.setenv("MONEYBOT_V3_PAPER_JOURNAL_PATH", str(journal))
    with staging_server() as url:
        code, _, body = get_response(url + "/paper-account")
        assert code == 503
        assert json.loads(body)["available"] is False
        journal.write_text("not sqlite")
        code, _, body = get_response(url + "/paper-account")
        assert code == 503
        assert json.loads(body)["available"] is False


def test_paper_account_dashboard_requires_explicit_journal_verification():
    with staging_server() as url:
        code, _, body = get_response(url)
    assert code == 200
    assert 'fetch("/paper-account", {cache: "no-store"})' in body
    assert "journal_only_not_broker_or_market_verified" in body
    assert "Paper account unavailable" in body
    assert "NOT broker verified" in body



def test_paper_account_reads_persisted_journal_without_enabling_trading(monkeypatch, tmp_path):
    """HTTP projection must survive reopening and never imply broker verification."""
    from paper_journal import PaperJournal

    journal_path = tmp_path / "paper-only.db"
    journal = PaperJournal(journal_path)
    assert journal.record("seed-1", "paper_deposit", "1000.25", {}) is True
    assert journal.record("draw-1", "paper_withdrawal", "75.10", {}) is True
    monkeypatch.setenv("MONEYBOT_V3_PAPER_JOURNAL_PATH", str(journal_path))

    with staging_server() as url:
        code, headers, body = get_response(url + "/paper-account")
        ready_code, _, ready_body = get_response(url + "/readyz")
        status_code, _, status_body = get_response(url + "/status")

    assert code == 200
    assert headers["Cache-Control"] == "no-store"
    data = json.loads(body)
    assert data["available"] is True
    assert data["source"] == "isolated_paper_journal"
    assert data["verification"] == "journal_only_not_broker_or_market_verified"
    assert data["cash"] == "925.15"
    assert data["deposits"] == "1000.25"
    assert data["withdrawals"] == "75.10"
    assert data["event_count"] == 2
    assert data["paper_trades"] is None
    assert data["performance"] is None
    assert data["trading_ready"] is False
    assert ready_code == 503
    assert json.loads(ready_body)["ready_for_automatic_paper_trading"] is False
    assert status_code == 200
    assert json.loads(status_body)["automatic_paper_trading"] is False
