"""Deployment provenance and read-only HTTP regression tests for V3 staging."""
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from paper_status_server import StatusHandler


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), StatusHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()


def request(port, method, path):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


@pytest.mark.parametrize("revision,expected", [
    ("a" * 40, "a" * 40),
    ("", None),
    ("A" * 40, None),
    ("z" * 40, None),
    ("a" * 39, None),
])
def test_version_provenance_fails_closed(server, monkeypatch, revision, expected):
    monkeypatch.setenv("RENDER_GIT_COMMIT", revision)
    status, headers, body = request(server, "GET", "/version")
    assert status == 200
    assert json.loads(body) == {"git_commit": expected}
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path,expected_status", [
    ("/", 200), ("/healthz", 200), ("/readyz", 503),
    ("/status", 200), ("/version", 200), ("/missing", 404),
])
def test_head_matches_get_without_body(server, path, expected_status):
    get_status, _, _ = request(server, "GET", path)
    head_status, head_headers, head_body = request(server, "HEAD", path)
    assert get_status == head_status == expected_status
    assert head_body == b""
    assert int(head_headers["Content-Length"]) >= 0


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"])
def test_no_mutating_or_tunneling_methods(server, method):
    status, _, body = request(server, method, "/orders")
    assert status == 405
    assert json.loads(body) == {"error": "read-only service"}
