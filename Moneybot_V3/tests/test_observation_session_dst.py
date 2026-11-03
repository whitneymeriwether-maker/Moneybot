"""Research-only observation journal timezone and session-boundary regressions."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from v3_observation_journal import PaperObservationJournal


NY = ZoneInfo("America/New_York")


def _record(journal, minute, *, received_at=None):
    return journal.record(
        feed="alpaca-iex", symbol="SPY", minute=minute,
        received_at=received_at or minute + timedelta(minutes=1, seconds=5),
        open="500.01", high="500.03", low="500.00", close="500.02",
        volume=100,
    )


@pytest.mark.parametrize("day,utc_open", [
    ((2026, 3, 6), 14),  # EST before spring DST transition
    ((2026, 3, 9), 13),  # EDT after spring DST transition
    ((2026, 10, 30), 13),  # EDT before fall DST transition
    ((2026, 11, 2), 14),  # EST after fall DST transition
])
def test_regular_session_open_uses_new_york_dst(tmp_path, day, utc_open):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    opening = datetime(*day, 9, 30, tzinfo=NY)
    assert opening.astimezone(timezone.utc).hour == utc_open
    assert _record(journal, opening)
    observed = journal.audited_latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=opening + timedelta(minutes=1, seconds=10),
    )
    assert observed["minute_utc"] == opening.astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    )


@pytest.mark.parametrize("hour,minute", [
    (9, 29), (16, 0), (16, 1),
])
def test_outside_regular_session_rejected(tmp_path, hour, minute):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    instant = datetime(2026, 11, 2, hour, minute, tzinfo=NY)
    with pytest.raises(ValueError, match="regular session"):
        _record(journal, instant)


def test_weekend_rejected_without_record(tmp_path):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    saturday = datetime(2026, 11, 7, 9, 30, tzinfo=NY)
    with pytest.raises(ValueError, match="regular session"):
        _record(journal, saturday)
    assert journal.audited_latest(
        feed="alpaca-iex", symbol="SPY", as_of=saturday + timedelta(minutes=2)
    ) is None


def test_equivalent_utc_and_local_minute_is_idempotent(tmp_path):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    local = datetime(2026, 11, 2, 9, 30, tzinfo=NY)
    assert _record(journal, local)
    assert _record(journal, local.astimezone(timezone.utc)) is False
    assert journal.audited_latest(
        feed="alpaca-iex", symbol="SPY", as_of=local + timedelta(minutes=2)
    ) is not None
