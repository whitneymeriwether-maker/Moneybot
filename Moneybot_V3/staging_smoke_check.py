"""Read-only, fail-closed smoke check for the isolated V3 staging deployment.

Only GET and HEAD are sent. This tool never creates a signal, paper fill,
order, account, or market-data subscription. It is NOT trading validation.
"""

import argparse
import json
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_URL = "https://moneybot-v3-staging.onrender.com"
_MAX_BODY = 16 * 1024


class _NoRedirect(HTTPRedirectHandler):
    """Never follow a redirect to a different service or host."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _json_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON status field")
        result[key] = value
    return result


def _base_url(url, *, allow_loopback):
    if type(url) is not str:
        raise ValueError("Invalid staging URL")
    parsed = urlsplit(url)
    if (
        parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or parsed.path not in ("", "/")
    ):
        raise ValueError("Staging URL must be a bare service origin")
    # No arbitrary host/port, even if a caller passes a plausible URL.
    if (
        parsed.scheme == "https"
        and parsed.hostname == "moneybot-v3-staging.onrender.com"
        and parsed.port is None
    ):
        return DEFAULT_URL
    if (
        allow_loopback and parsed.scheme == "http"
        and parsed.hostname in ("127.0.0.1", "localhost")
        and parsed.port is not None
        and 1 <= parsed.port <= 65535
    ):
        return f"http://{parsed.hostname}:{parsed.port}"
    raise ValueError("Only the isolated V3 staging host is permitted")


def _fetch(opener, url, method, expected, content_type, timeout):
    request = Request(url, method=method)
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        code = response.status
        headers = response.headers
        payload = response.read(_MAX_BODY + 1)
    if code != expected:
        raise RuntimeError(f"Staging {method} {urlsplit(url).path}: HTTP {code}, expected {expected}")
    if len(payload) > _MAX_BODY:
        raise RuntimeError("Oversized staging response")
    if headers.get_content_type() != content_type:
        raise RuntimeError("Unexpected staging response content type")
    if headers.get("Cache-Control") != "no-store":
        raise RuntimeError("Staging response is cacheable")
    if headers.get("X-Content-Type-Options") != "nosniff":
        raise RuntimeError("Staging response lacks nosniff")
    if method == "HEAD":
        if payload or not (headers.get("Content-Length") or "").isdecimal() or int(headers["Content-Length"]) <= 0:
            raise RuntimeError("Invalid staging HEAD response")
        return None
    if not payload:
        raise RuntimeError("Empty staging GET response")
    return payload


def smoke_check(url=DEFAULT_URL, *, allow_loopback=False, timeout=10):
    """Verify the service is alive AND unequivocally NOT trading-ready.

    A successful result is only a deployment safety smoke-test. The caller
    must not interpret it as proof of paper execution or profitability.
    """
    if type(timeout) not in (int, float) or not 0 < timeout <= 30:
        raise ValueError("Invalid smoke-check timeout")
    base = _base_url(url, allow_loopback=allow_loopback)
    opener = build_opener(_NoRedirect())
    for path, expected in (("/healthz", 200), ("/readyz", 503)):
        _fetch(opener, base + path, "HEAD", expected, "application/json", timeout)

    def read_json(path, expected):
        raw = _fetch(opener, base + path, "GET", expected, "application/json", timeout)
        try:
            data = json.loads(raw, object_pairs_hook=_json_no_duplicates)
        except (ValueError, UnicodeDecodeError) as error:
            raise RuntimeError("Malformed staging JSON") from error
        if type(data) is not dict:
            raise RuntimeError("Unexpected staging JSON structure")
        return data

    health = read_json("/healthz", 200)
    status = read_json("/status", 200)
    ready = read_json("/readyz", 503)
    homepage = _fetch(opener, base + "/", "GET", 200, "text/html", timeout)
    if (
        health.get("service") != "up"
        or health.get("trading_state") != "NOT_ACTIVATED"
        or status.get("application") != "Moneybot V3"
        or status.get("trading_state") != "NOT_ACTIVATED"
        or status.get("automatic_paper_trading") is not False
        or status.get("real_money_trading") is not False
        or status.get("market_data") != "NOT_CONNECTED"
        or status.get("persistent_paper_ledger") != "NOT_CONNECTED"
        or status.get("execution_time_risk_gate") != "NOT_CONNECTED"
        or ready.get("ready_for_automatic_paper_trading") is not False
        or b"NOT ACTIVATED" not in homepage
        or b"No live-money or paper orders" not in homepage
    ):
        raise RuntimeError("Staging safety assertions failed")
    return {"staging_reachable": True, "trading_state": "NOT_ACTIVATED",
            "automatic_paper_trading": False, "trading_ready": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL,
                        help="Isolated V3 staging origin (no arbitrary remote hosts)")
    args = parser.parse_args(argv)
    try:
        result = smoke_check(args.url)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"V3 staging smoke check FAILED: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
