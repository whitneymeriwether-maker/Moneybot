#!/usr/bin/env python3
"""Read-only acceptance probe for isolated Moneybot V3 staging.

Usage: python Moneybot_V3/verify_deployed_dashboard.py https://moneybot-v3-staging.onrender.com
Never submits orders or modifies server state. A 200 health check is insufficient.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def verify(base):
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme != "https" or not parsed.netloc or parsed.username
            or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ValueError("Expected a bare HTTPS staging origin")

    def get(path):
        request = urllib.request.Request(
            base.rstrip("/") + path,
            headers={"Accept": "application/json", "Cache-Control": "no-cache"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError(f"{path}: HTTP {response.status}")
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise RuntimeError(f"{path}: oversized response")
            return body, response.headers.get("Content-Type", "")

    html, _ = get("/")
    for label in (b"System health", b"Account state", b"Paper trades",
                  b"Risk limits", b"Performance", b"NOT ACTIVATED"):
        if label not in html:
            raise RuntimeError(f"Dashboard missing {label.decode()}")

    def document(path):
        raw, content_type = get(path)
        if "json" not in content_type.lower():
            raise RuntimeError(f"{path}: unexpected content type")
        return json.loads(raw)

    health = document("/healthz")
    status = document("/status")
    if health.get("service") != "up" or health.get("trading_state") != "NOT_ACTIVATED":
        raise RuntimeError("Health response inconsistent")
    required = {
        "application": "Moneybot V3",
        "trading_state": "NOT_ACTIVATED",
        "automatic_paper_trading": False,
        "real_money_trading": False,
        "market_data": "NOT_CONNECTED",
        "persistent_paper_ledger": "NOT_CONNECTED",
        "execution_time_risk_gate": "NOT_CONNECTED",
    }
    if any(status.get(k) != v for k, v in required.items()):
        raise RuntimeError("Trading status violates disabled staging contract")
    # Trading readiness must never succeed on this diagnostic-only service.
    try:
        get("/readyz")
    except urllib.error.HTTPError as exc:
        if exc.code != 503:
            raise RuntimeError(f"Readiness expected 503, received {exc.code}") from exc
    else:
        raise RuntimeError("Trading readiness unexpectedly succeeded")
    print("PASS: dashboard sections, liveness, disabled integration state, and fail-closed readiness")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: verify_deployed_dashboard.py https://staging-host")
    try:
        verify(sys.argv[1])
    except Exception as exc:
        sys.exit(f"FAIL: {exc}")
