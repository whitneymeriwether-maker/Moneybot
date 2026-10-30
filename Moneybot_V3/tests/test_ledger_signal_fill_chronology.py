"""Synthetic offline tests: a signal must not predate later paper fills."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from paper_ledger import PaperLedger
from v3_decision import Candidate
from v3_ledger_advisory import review_ledger_research_proposal


PAYLOAD = json.dumps({
    "action": "BUY", "thesis": "Synthetic observed breakout",
    "risks": "Synthetic gap and slippage",
    "evidence_ids": ["bar:SPY:1"], "confidence": 0.7,
})


def _review(ledger, now, signal_at, marks):
    return review_ledger_research_proposal(
        PAYLOAD, ledger=ledger, marks=marks, as_of=now,
        peak_equity="1000.00", realized_pnl_today="0.00",
        trusted_evidence_ids=("bar:SPY:1",),
        candidate=Candidate(
            "SPY", signal_at, 100.0, True, True, 2.0, True, 1.0, 30,
        ),
    )


def _buy(ledger, when, symbol="QQQ", event_id="buy"):
    ledger.record_fill(
        event_id=event_id, timestamp=when, symbol=symbol,
        side="BUY", quantity=1, price="100.00",
    )


def _marks(now, symbol="QQQ"):
    return {symbol: {"price": "100.00", "timestamp": now}}


def test_empty_paper_account_has_no_last_fill_and_allows_fresh_signal(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "empty.sqlite3")
    assert ledger.marked_snapshot({}, as_of=now)["last_fill_timestamp_utc"] is None
    result = _review(ledger, now, now - timedelta(seconds=2), {})
    assert result.decision.approved
    assert ledger.snapshot()["fill_count"] == 0


def test_fill_before_signal_is_eligible_for_review(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "before.sqlite3")
    _buy(ledger, now - timedelta(seconds=20))
    result = _review(ledger, now, now - timedelta(seconds=10), _marks(now))
    assert result.decision.approved
    assert ledger.snapshot()["fill_count"] == 1


def test_later_unrelated_symbol_fill_invalidates_old_signal(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "unrelated.sqlite3")
    _buy(ledger, now - timedelta(seconds=5), symbol="QQQ")
    result = _review(ledger, now, now - timedelta(seconds=10), _marks(now))
    assert result.proposal is None
    assert not result.decision.approved
    assert result.decision.reason == "Unverified ledger snapshot or paper risk history"
    assert ledger.snapshot()["fill_count"] == 1


def test_later_same_symbol_fill_invalidates_old_signal(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "same.sqlite3")
    _buy(ledger, now - timedelta(seconds=5), symbol="SPY")
    result = _review(ledger, now, now - timedelta(seconds=10), _marks(now, "SPY"))
    assert result.proposal is None
    assert not result.decision.approved
    assert ledger.snapshot()["fill_count"] == 1


def test_signal_at_same_instant_as_fill_is_not_rejected(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "same-time.sqlite3")
    instant = now - timedelta(seconds=5)
    _buy(ledger, instant)
    result = _review(ledger, now, instant, _marks(now))
    assert result.decision.approved


def test_later_full_exit_still_invalidates_old_signal(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "exited.sqlite3")
    _buy(ledger, now - timedelta(seconds=20), symbol="SPY")
    ledger.record_fill(
        event_id="sell", timestamp=now - timedelta(seconds=5),
        symbol="SPY", side="SELL", quantity=1, price="100.00",
    )
    assert ledger.snapshot()["positions"] == {}
    result = _review(ledger, now, now - timedelta(seconds=10), {})
    assert result.proposal is None
    assert not result.decision.approved
    assert ledger.snapshot()["fill_count"] == 2


def test_last_fill_timestamp_is_canonical_utc_across_timezones(tmp_path):
    now = datetime.now(timezone.utc)
    instant = now - timedelta(seconds=5)
    ledger = PaperLedger(tmp_path / "timezone.sqlite3")
    _buy(ledger, instant.astimezone(ZoneInfo("America/New_York")))
    marked = ledger.marked_snapshot(_marks(now), as_of=now)
    assert marked["last_fill_timestamp_utc"] == instant.isoformat(timespec="microseconds")
    result = _review(ledger, now, now - timedelta(seconds=10), _marks(now))
    assert not result.decision.approved
