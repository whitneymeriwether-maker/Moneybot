"""Closed-trade replay must not conceal insolvency by reordering exits."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v3_evaluation import ClosedTrade, evaluate_closed_trades, compare_paper_strategies


def trade(pnl=5, *, symbol="AMD", entry="2026-01-02T14:30:00Z",
          exit_at="2026-01-02T14:31:00Z"):
    return ClosedTrade(symbol, pnl, entry, exit_at)


def test_explicit_offset_and_fractional_utc_instants_are_supported():
    records = [
        trade(10, entry="2026-01-02T20:00:00+05:30",
              exit_at="2026-01-02T09:31:00.000001-05:00"),
        trade(-2, entry="2026-01-02T14:31:01Z",
              exit_at="2026-01-02T14:32:00Z"),
    ]
    result = evaluate_closed_trades(records, 1000)
    assert result["net_pnl"] == 8
    assert result["trade_count"] == 2


@pytest.mark.parametrize("symbol", ["amd", "ＡMD", "A B", "", "ABCDEFGHIJK", None])
def test_rejects_invalid_ticker_metadata(symbol):
    with pytest.raises(ValueError, match="Invalid closed trade symbol"):
        evaluate_closed_trades([trade(symbol=symbol)], 1000)


@pytest.mark.parametrize("stamp", [
    "entry", "20260102T143000Z", "2026-01-02 14:30:00Z",
    "2026-01-02T14:30Z", "2026-01-02T14:30:00",
    "2026-01-02T14:30:00+00:00:00",
    "2026-01-02T14:30:00.1234567Z",
    "2026-02-30T14:30:00Z", "2026-01-02T14:30:00+24:00",
    None, 123, True,
])
@pytest.mark.parametrize("field", ["entry", "exit_at"])
def test_rejects_noncanonical_or_unparseable_trade_timestamps(stamp, field):
    kwargs = {field: stamp}
    with pytest.raises(ValueError, match="Invalid closed trade timestamp"):
        evaluate_closed_trades([trade(**kwargs)], 1000)


@pytest.mark.parametrize("entry,exit_at", [
    ("2026-01-02T14:31:00Z", "2026-01-02T14:31:00Z"),
    ("2026-01-02T14:32:00Z", "2026-01-02T14:31:00Z"),
    ("2026-01-02T20:01:00+05:30", "2026-01-02T09:30:00-05:00"),
])
def test_rejects_zero_or_negative_trade_duration(entry, exit_at):
    with pytest.raises(ValueError, match="exit must follow entry"):
        evaluate_closed_trades([trade(entry=entry, exit_at=exit_at)], 1000)


@pytest.mark.parametrize("later_exit", [
    "2026-01-02T14:31:00Z",
    "2026-01-02T14:30:30Z",
    "2026-01-02T09:31:00-05:00",
])
def test_rejects_duplicate_or_backwards_exit_order(later_exit):
    first = trade(-999, exit_at="2026-01-02T14:31:00Z")
    second = trade(100, entry="2026-01-02T14:29:00Z",
                   exit_at=later_exit)
    with pytest.raises(ValueError, match="strictly increasing exits"):
        evaluate_closed_trades([first, second], 1000)


def test_strategy_comparison_fails_closed_on_reordered_baseline_or_ai():
    later_win = trade(100, entry="2026-01-02T14:30:00Z",
                      exit_at="2026-01-02T14:34:00Z")
    earlier_loss = trade(-1000, entry="2026-01-02T14:29:00Z",
                         exit_at="2026-01-02T14:32:00Z")
    for baseline, ai in (([later_win, earlier_loss], []),
                         ([], [later_win, earlier_loss])):
        with pytest.raises(ValueError, match="strictly increasing exits"):
            compare_paper_strategies(baseline, ai, 1000)
    with pytest.raises(ValueError, match="after cash-funded account depletion"):
        evaluate_closed_trades([earlier_loss, later_win], 1000)


def test_valid_class_share_ticker_and_empty_replay():
    assert evaluate_closed_trades([trade(symbol="BRK.B")], 1000)["trade_count"] == 1
    assert evaluate_closed_trades([], 1000)["trade_count"] == 0


@pytest.mark.parametrize("records", [None, "invalid", {}, iter(())])
def test_rejects_nonmaterialized_trade_sequences(records):
    with pytest.raises(ValueError, match="list or tuple"):
        evaluate_closed_trades(records, 1000)
