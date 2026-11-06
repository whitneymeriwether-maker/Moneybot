"""Independent staging smoke checks must fail closed and never send orders."""

import pytest

import paper_status_server
from staging_smoke_check import _base_url, main, smoke_check
from test_paper_status_server import staging_server


def test_local_staging_smoke_passes_but_never_claims_trading_readiness():
    with staging_server() as url:
        result = smoke_check(url, allow_loopback=True)
    assert result == {
        "staging_reachable": True,
        "trading_state": "NOT_ACTIVATED",
        "automatic_paper_trading": False,
        "trading_ready": False,
    }


@pytest.mark.parametrize("url", [
    "https://moneybot-7l6j.onrender.com",
    "https://moneybot-v3-staging.onrender.com.evil.example",
    "http://moneybot-v3-staging.onrender.com",
    "https://user:password@moneybot-v3-staging.onrender.com",
    "https://moneybot-v3-staging.onrender.com/orders",
    "https://moneybot-v3-staging.onrender.com/?token=secret",
    "https://moneybot-v3-staging.onrender.com:8443",
    "http://127.0.0.1:8000",
])
def test_refuses_unapproved_targets(url):
    with pytest.raises(ValueError):
        _base_url(url, allow_loopback=False)


def test_staging_status_cannot_silently_report_activation(monkeypatch):
    with staging_server() as url:
        monkeypatch.setitem(paper_status_server._STATUS, "automatic_paper_trading", True)
        with pytest.raises(RuntimeError, match="safety assertions"):
            smoke_check(url, allow_loopback=True)


def test_staging_readiness_cannot_silently_flip_to_200(monkeypatch):
    original = paper_status_server.StatusHandler.do_GET

    def incorrect_ready(self):
        if self.path == "/readyz":
            self._send(200, '{"ready_for_automatic_paper_trading":true}',
                       "application/json; charset=utf-8")
        else:
            original(self)

    with staging_server() as url:
        monkeypatch.setattr(paper_status_server.StatusHandler, "do_GET",
                            incorrect_ready)
        with pytest.raises(RuntimeError, match="HTTP 200, expected 503"):
            smoke_check(url, allow_loopback=True)


def test_cli_does_not_permit_loopback_or_other_services(capsys):
    assert main(["--url", "http://127.0.0.1:8000"]) == 1
    assert "FAILED" in capsys.readouterr().err


def test_smoke_rejects_dashboard_missing_paper_data_disclosure(monkeypatch):
    original = paper_status_server._HTML
    monkeypatch.setattr(
        paper_status_server, "_HTML",
        original.replace("Trade count unknown, not zero", "Trade count: 0"),
    )
    with staging_server() as url:
        with pytest.raises(RuntimeError, match="safety assertions"):
            smoke_check(url, allow_loopback=True)


def test_smoke_rejects_dashboard_without_live_health_polling(monkeypatch):
    original = paper_status_server._HTML
    monkeypatch.setattr(
        paper_status_server, "_HTML",
        original.replace("setInterval(refreshHealth, 30000)", ""),
    )
    with staging_server() as url:
        with pytest.raises(RuntimeError, match="safety assertions"):
            smoke_check(url, allow_loopback=True)
