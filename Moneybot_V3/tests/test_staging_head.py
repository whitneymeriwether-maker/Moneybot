"""HEAD probes must preserve staging liveness and fail-closed readiness."""

import json

from test_paper_status_server import get_response, staging_server


def test_head_root_and_liveness_are_successful_without_body():
    with staging_server() as url:
        for path in ("/", "/healthz", "/status"):
            code, headers, body = get_response(url + path, method="HEAD")
            assert code == 200
            assert body == ""
            assert int(headers["Content-Length"]) > 0
            assert headers["Cache-Control"] == "no-store"
            assert headers["X-Content-Type-Options"] == "nosniff"


def test_head_readiness_stays_unavailable_without_body():
    with staging_server() as url:
        code, headers, body = get_response(url + "/readyz", method="HEAD")
        assert code == 503
        assert body == ""
        assert headers.get_content_type() == "application/json"
        assert int(headers["Content-Length"]) > 0
        # GET still reports the same unactivated status and a valid JSON body.
        code, _, body = get_response(url + "/readyz")
        assert code == 503
        assert json.loads(body)["ready_for_automatic_paper_trading"] is False


def test_head_unknown_route_does_not_become_a_health_check():
    with staging_server() as url:
        code, _, body = get_response(url + "/api/broker/orders", method="HEAD")
        assert code == 404
        assert body == ""
