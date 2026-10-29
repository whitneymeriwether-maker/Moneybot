"""Strict offline chronological fold and fixed-baseline regression tests."""

import sys
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.walk_forward import (
    build_research_folds, evaluate_fixed_baseline_folds,
)

NY = ZoneInfo("America/New_York")


def make_bars(session_count=10):
    bars = []
    day = date(2026, 10, 12)
    for _ in range(session_count):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        start = datetime.combine(day, time(9, 30), tzinfo=NY)
        for minute in range(390):
            bars.append(SimpleNamespace(
                timestamp=start + timedelta(minutes=minute),
                open=100.0, high=101.0, low=99.0, close=100.0,
                volume=1000,
            ))
        day += timedelta(days=1)
    return bars


def test_folds_are_chronological_embargoed_and_test_disjoint():
    bars = make_bars()
    folds = build_research_folds(
        bars, train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    assert len(folds) == 3
    assert [len(f.test_bars) for f in folds] == [780, 780, 780]
    assert [len(f.train_bars) for f in folds] == [1170] * 3
    all_test_dates = []
    for fold in folds:
        assert max(fold.train_dates) < min(fold.embargo_dates)
        assert max(fold.embargo_dates) < min(fold.test_dates)
        assert {b.timestamp.date() for b in fold.test_bars} == set(fold.test_dates)
        assert {b.timestamp.date() for b in fold.train_bars} == set(fold.train_dates)
        all_test_dates.extend(fold.test_dates)
    assert len(all_test_dates) == len(set(all_test_dates))


def test_fixed_baseline_scores_only_test_bars(monkeypatch):
    bars = make_bars(6)
    fold = build_research_folds(
        bars, train_sessions=3, embargo_sessions=1, test_sessions=2
    )[0]
    seen = []

    def capture(test_bars):
        seen.extend(b.timestamp.date() for b in test_bars)
        return []

    monkeypatch.setattr("backtesting.walk_forward.generate_breakout_signals", capture)
    results = evaluate_fixed_baseline_folds((fold,))
    assert set(seen) == set(fold.test_dates)
    assert not set(seen) & set(fold.train_dates + fold.embargo_dates)
    assert results[0].trade_count == 0
    assert results[0].ending_cash == 1000.0


def test_fixed_baseline_constant_prices_do_not_create_fake_profit():
    folds = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    result, = evaluate_fixed_baseline_folds(folds)
    assert result.signal_count == 0
    assert result.net_pnl == 0
    assert result.return_pct == 0


@pytest.mark.parametrize("options", [
    {"train_sessions": 0, "test_sessions": 2},
    {"train_sessions": True, "test_sessions": 2},
    {"train_sessions": 2, "test_sessions": 0},
    {"train_sessions": 2, "test_sessions": 2, "embargo_sessions": -1},
    {"train_sessions": 2, "test_sessions": 2, "embargo_sessions": True},
    {"train_sessions": 2, "test_sessions": 2, "step_sessions": 1},
    {"train_sessions": 2, "test_sessions": 2, "step_sessions": 2.0},
])
def test_invalid_fold_configuration_fails_closed(options):
    with pytest.raises(ValueError):
        build_research_folds(make_bars(6), **options)


@pytest.mark.parametrize("mutation", [
    "missing_interior", "truncated_close", "zero_volume",
    "bad_ohlc", "duplicate", "reverse",
])
def test_invalid_or_sparse_market_bars_fail_closed(mutation):
    bars = make_bars(6)
    if mutation == "missing_interior":
        del bars[10]
    elif mutation == "truncated_close":
        del bars[389]
    elif mutation == "zero_volume":
        bars[10].volume = 0
    elif mutation == "bad_ohlc":
        bars[10].low = 102
    elif mutation == "duplicate":
        bars.insert(10, bars[9])
    elif mutation == "reverse":
        bars[9], bars[10] = bars[10], bars[9]
    with pytest.raises(ValueError):
        build_research_folds(
            bars, train_sessions=3, embargo_sessions=1, test_sessions=2
        )


def test_missing_entire_session_requires_explicit_calendar_to_detect():
    bars = make_bars(7)
    first = bars[0].timestamp.date()
    last = bars[-1].timestamp.date()
    # Remove a complete weekday session. Completeness checks alone cannot
    # distinguish the gap from a scheduled closure.
    missing = date(2026, 10, 14)
    bars = [b for b in bars if b.timestamp.date() != missing]
    assert build_research_folds(
        bars, train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    with pytest.raises(ValueError, match="calendar mismatch"):
        build_research_folds(
            bars, train_sessions=3, embargo_sessions=1, test_sessions=2,
            expected_session_span=(first, last), closed_sessions=(),
        )


def test_overlapping_test_windows_rejected_even_if_supplied_manually():
    folds = build_research_folds(
        make_bars(8), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    with pytest.raises(ValueError, match="Overlapping"):
        evaluate_fixed_baseline_folds((folds[0], replace(folds[1], test_dates=folds[0].test_dates)))


def test_insufficient_sessions_does_not_return_empty_success():
    with pytest.raises(ValueError, match="Insufficient sessions"):
        build_research_folds(
            make_bars(3), train_sessions=2, embargo_sessions=1, test_sessions=2
        )


def test_calendar_requires_explicit_span():
    with pytest.raises(ValueError, match="requires"):
        build_research_folds(
            make_bars(6), train_sessions=3, test_sessions=2,
            closed_sessions=(),
        )

@pytest.mark.parametrize("corruption", ["empty", "training_bars"])
def test_evaluator_rejects_forged_out_of_sample_bars(corruption):
    fold, = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    bad_bars = () if corruption == "empty" else fold.train_bars[:780]
    forged = replace(fold, test_bars=bad_bars)
    with pytest.raises(ValueError, match="test bars do not match test dates"):
        evaluate_fixed_baseline_folds((forged,))


@pytest.mark.parametrize("corruption", [
    "duplicate_minute", "missing_minute", "bad_price",
    "bad_ohlc", "zero_volume", "fractional_volume", "off_minute",
])
def test_evaluator_revalidates_manually_supplied_test_tape(corruption):
    fold, = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    bars = list(fold.test_bars)
    if corruption == "duplicate_minute":
        bars[10] = bars[9]
    elif corruption == "missing_minute":
        bars[10] = bars[11]
    else:
        values = vars(bars[10]).copy()
        if corruption == "bad_price":
            values["close"] = float("nan")
        elif corruption == "bad_ohlc":
            values["low"] = 102.0
        elif corruption == "zero_volume":
            values["volume"] = 0
        elif corruption == "fractional_volume":
            values["volume"] = 100.5
        elif corruption == "off_minute":
            values["timestamp"] += timedelta(seconds=30)
        bars[10] = SimpleNamespace(**values)
    with pytest.raises(ValueError):
        evaluate_fixed_baseline_folds((replace(fold, test_bars=tuple(bars)),))


@pytest.mark.parametrize("corruption", [
    "training_after_test", "embargo_after_test",
    "duplicate_training_date", "weekend_test_date",
])
def test_evaluator_rejects_forged_fold_chronology(corruption):
    fold, = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    if corruption == "training_after_test":
        fold = replace(fold, train_dates=fold.train_dates + (date(2026, 11, 2),))
    elif corruption == "embargo_after_test":
        fold = replace(fold, embargo_dates=(date(2026, 11, 2),))
    elif corruption == "duplicate_training_date":
        fold = replace(fold, train_dates=fold.train_dates + (fold.train_dates[-1],))
    elif corruption == "weekend_test_date":
        fold = replace(fold, test_dates=(date(2026, 10, 17), fold.test_dates[-1]))
    with pytest.raises(ValueError):
        evaluate_fixed_baseline_folds((fold,))


@pytest.mark.parametrize("corruption", [
    "empty", "training_from_test", "duplicate_minute",
    "bad_price", "bad_ohlc", "zero_volume", "fractional_volume",
    "off_minute",
])
def test_evaluator_revalidates_claimed_training_tape(corruption):
    fold, = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    bars = list(fold.train_bars)
    if corruption == "empty":
        bars = []
    elif corruption == "training_from_test":
        bars = list(fold.test_bars) + bars[780:]
    elif corruption == "duplicate_minute":
        bars[10] = bars[9]
    else:
        values = vars(bars[10]).copy()
        if corruption == "bad_price":
            values["close"] = float("inf")
        elif corruption == "bad_ohlc":
            values["high"] = 98.0
        elif corruption == "zero_volume":
            values["volume"] = 0
        elif corruption == "fractional_volume":
            values["volume"] = 1.5
        elif corruption == "off_minute":
            values["timestamp"] += timedelta(seconds=30)
        bars[10] = SimpleNamespace(**values)
    with pytest.raises(ValueError, match="train"):
        evaluate_fixed_baseline_folds(
            (replace(fold, train_bars=tuple(bars)),)
        )


def test_evaluator_rejects_reversed_nonoverlapping_test_windows():
    folds = build_research_folds(
        make_bars(8), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    # Reordering otherwise valid, disjoint folds must not look chronological.
    with pytest.raises(ValueError, match="chronological"):
        evaluate_fixed_baseline_folds((
            replace(folds[1], number=1),
            replace(folds[0], number=2),
        ))


@pytest.mark.parametrize("bad_number", [0, -1, True, 1.0, "1"])
def test_evaluator_rejects_invalid_fold_identifiers(bad_number):
    fold, = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    with pytest.raises(ValueError, match="numbers"):
        evaluate_fixed_baseline_folds((replace(fold, number=bad_number),))


def test_evaluator_rejects_reused_fold_identifier():
    folds = build_research_folds(
        make_bars(8), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    with pytest.raises(ValueError, match="numbers"):
        evaluate_fixed_baseline_folds((
            folds[0], replace(folds[1], number=folds[0].number),
        ))


@pytest.mark.parametrize("field,bad_dates", [
    ("test_dates", ([date(2026, 10, 16)],)),
    ("test_dates", ([],)),
    ("train_dates", [date(2026, 10, 12)]),
    ("embargo_dates", ([date(2026, 10, 15)],)),
    ("test_dates", (datetime(2026, 10, 16),)),
])
def test_evaluator_rejects_malformed_date_containers_cleanly(field, bad_dates):
    fold, = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    with pytest.raises(ValueError, match="session dates"):
        evaluate_fixed_baseline_folds((replace(fold, **{field: bad_dates}),))


def test_evaluator_subtracts_both_commission_sides_from_fold_returns(monkeypatch):
    from backtesting.trade_simulator import SimulatedTrade

    fold, = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    seen = []

    def fake_simulate(bars, signals, **kwargs):
        seen.append(kwargs["commission_per_share"])
        return [SimulatedTrade(
            entry_time=fold.test_bars[0].timestamp,
            exit_time=fold.test_bars[1].timestamp,
            entry_price=100, exit_price=105, quantity=2,
            exit_reason="target", entry_fee=0.5, exit_fee=0.5,
        )]

    monkeypatch.setattr("backtesting.walk_forward.generate_breakout_signals", lambda bars: [])
    monkeypatch.setattr("backtesting.walk_forward.simulate_trades", fake_simulate)
    result, = evaluate_fixed_baseline_folds(
        (fold,), starting_cash=1000, commission_per_share=0.25,
    )
    assert seen == [0.25]
    assert result.trade_count == 1
    assert result.net_pnl == 9
    assert result.ending_cash == 1009
    assert result.return_pct == 0.9


def test_fold_evaluator_forwards_assumed_spread_to_simulator(monkeypatch):
    fold, = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    observed = []

    def capture(bars, signals, **kwargs):
        observed.append(kwargs["spread_pct"])
        return []

    monkeypatch.setattr("backtesting.walk_forward.simulate_trades", capture)
    evaluate_fixed_baseline_folds((fold,), spread_pct=0.006)
    assert observed == [0.006]


def test_fold_evaluator_forwards_participation_limit_to_simulator(monkeypatch):
    fold, = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    observed = []

    def capture(bars, signals, **kwargs):
        observed.append(kwargs["max_participation"])
        return []

    monkeypatch.setattr("backtesting.walk_forward.simulate_trades", capture)
    evaluate_fixed_baseline_folds((fold,), max_participation=0.025)
    assert observed == [0.025]


@pytest.mark.parametrize("invalid", [
    None, True, "0.1", 0, -0.01, 1.01, float("nan"),
    float("inf"), 10 ** 400,
])
def test_fold_evaluator_rejects_invalid_participation_limit(invalid):
    with pytest.raises(ValueError, match="Invalid maximum participation"):
        evaluate_fixed_baseline_folds((), max_participation=invalid)


@pytest.mark.parametrize("role", ["train", "test"])
def test_evaluator_rejects_seconds_bearing_offset_in_fold_tape(role):
    # Every displayed local minute is :00, but UTC instants are at :30.
    # A hand-built fold must not evade the CSV reader's UTC alignment check.
    fold, = build_research_folds(
        make_bars(6), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    field = role + "_bars"
    misleading_offset = timezone(timedelta(hours=-4, seconds=-30))
    corrupted = tuple(
        SimpleNamespace(**{
            **vars(bar),
            "timestamp": bar.timestamp.replace(tzinfo=misleading_offset),
        })
        for bar in getattr(fold, field)
    )
    with pytest.raises(ValueError, match=role):
        evaluate_fixed_baseline_folds((replace(fold, **{field: corrupted}),))


def test_evaluator_rejects_omitted_or_noninitial_fold_identifiers():
    # Public hand-built fold sequences must not silently omit a losing fold.
    folds = build_research_folds(
        make_bars(8), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    assert len(folds) == 2
    with pytest.raises(ValueError, match="consecutive"):
        evaluate_fixed_baseline_folds((replace(folds[0], number=2),))
    with pytest.raises(ValueError, match="consecutive"):
        evaluate_fixed_baseline_folds((folds[0], replace(folds[1], number=3)))
