"""Synthetic offline regressions for replay-derived NY trading-day PnL."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from paper_ledger import PaperLedger
from v3_decision import Candidate
from v3_ledger_advisory import review_ledger_research_proposal


NY = ZoneInfo("America/New_York")
PAYLOAD = json.dumps({
    "action": "BUY", "thesis": "Synthetic breakout",
    "risks": "Synthetic price gap", "evidence_ids": ["bar:SPY:1"],
    "confidence": 0.7,
})


def _review(ledger, now, daily):
    return review_ledger_research_proposal(
        PAYLOAD, ledger=ledger, marks={}, as_of=now,
        peak_equity="1000.00", realized_pnl_today=daily,
        trusted_evidence_ids=("bar:SPY:1",),
        candidate=Candidate(
            "SPY", now - timedelta(seconds=1), 100.0,
            True, True, 2.0, True, 1.0, 1,
        ),
    )


def _round_trip(ledger, buy_time, sell_time, price="70.00"):
    ledger.record_fill(
        event_id="test-buy", timestamp=buy_time,
        symbol="SPY", side="BUY", quantity=1, price="100.00",
    )
    ledger.record_fill(
        event_id="test-sell", timestamp=sell_time,
        symbol="SPY", side="SELL", quantity=1, price=price,
    )


@pytest.mark.parametrize("fabricated", ["-30.00", "30.00", "0.01"])
def test_empty_ledger_rejects_unreconciled_daily_pnl(tmp_path, fabricated):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "empty.sqlite3")
    result = _review(ledger, now, fabricated)
    assert result.proposal is None
    assert not result.decision.approved
    assert result.decision.reason == "Unverified ledger snapshot or paper risk history"
    assert ledger.audit_history()["audited_fills"] == 0


def test_cannot_hide_a_recorded_same_day_loss(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "loss.sqlite3")
    # Same-instant synthetic fills keep this day-boundary test deterministic.
    _round_trip(ledger, now, now)
    result = _review(ledger, now, "0.00")
    assert not result.decision.approved
    assert result.proposal is None
    assert ledger.audit_history()["realized_pnl"] == "-30.00"
    actual = _review(ledger, now, "-30.00")
    assert not actual.decision.approved
    assert actual.decision.reason == "Daily realized-loss circuit breaker"


def test_yesterday_loss_does_not_masquerade_as_today_loss(tmp_path):
    now = datetime.now(timezone.utc)
    yesterday = now.astimezone(NY).date() - timedelta(days=1)
    prior_noon = datetime.combine(
        yesterday, datetime.min.time(), tzinfo=NY,
    ).replace(hour=12).astimezone(timezone.utc)
    ledger = PaperLedger(tmp_path / "yesterday.sqlite3")
    _round_trip(ledger, prior_noon, prior_noon + timedelta(seconds=1))
    result = _review(ledger, now, "0.00")
    assert result.proposal is not None
    assert result.decision.approved
    assert ledger.audit_history()["realized_pnl"] == "-30.00"


def test_replay_boundary_respects_new_york_dst_midnight(tmp_path):
    ledger = PaperLedger(tmp_path / "dst.sqlite3")
    # On 2026-11-01 New York falls back: midnight is 04:00 UTC.
    _round_trip(
        ledger,
        datetime(2026, 11, 1, 3, 59, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 1, 4, 1, 0, tzinfo=timezone.utc),
    )
    start = datetime(2026, 11, 1, tzinfo=NY).astimezone(timezone.utc)
    assert start == datetime(2026, 11, 1, 4, tzinfo=timezone.utc)
    audit = ledger.audit_history(realized_since=start)
    assert audit["realized_since"] == "-30.00"
    assert audit["realized_pnl"] == "-30.00"
    assert ledger.audit_history(realized_since=start + timedelta(minutes=2))["realized_since"] == "0.00"


def test_replay_rejects_naive_risk_day_boundary(tmp_path):
    ledger = PaperLedger(tmp_path / "naive.sqlite3")
    with pytest.raises(ValueError, match="timezone-aware"):
        ledger.audit_history(realized_since=datetime(2026, 11, 1))
