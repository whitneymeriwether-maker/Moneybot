"""Cash-only research cannot verify funding for overlapping closed positions.

The evaluator has no opening notionals or reserved-cash history. Reject
overlapping intervals even when the realized exits are correctly ordered.
No broker, market-data provider, or network access is used.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v3_evaluation import ClosedTrade, compare_paper_strategies, evaluate_closed_trades


def _trade(symbol, pnl, entry, exit_at):
    return ClosedTrade(symbol, pnl, entry, exit_at)


@pytest.mark.parametrize("second_symbol", ["AMD", "MSFT"])
def test_overlapping_positions_with_increasing_exits_are_rejected(second_symbol):
    trades = [
        _trade("AMD", 10, "2026-01-02T14:30:00Z", "2026-01-02T14:34:00Z"),
        _trade(second_symbol, 20, "2026-01-02T14:33:00Z", "2026-01-02T14:35:00Z"),
    ]
    with pytest.raises(ValueError, match="overlap"):
        evaluate_closed_trades(trades, 1000)


def test_offset_equivalent_subsecond_overlap_is_rejected():
    trades = [
        _trade("AMD", 1, "2026-01-02T09:30:00-05:00",
               "2026-01-02T14:31:00.000001Z"),
        _trade("MSFT", 2, "2026-01-02T14:31:00Z",
               "2026-01-02T14:32:00Z"),
    ]
    with pytest.raises(ValueError, match="overlap"):
        evaluate_closed_trades(trades, 1000)


@pytest.mark.parametrize("side", ["baseline", "ai"])
def test_strategy_comparison_rejects_overlapping_side(side):
    trades = [
        _trade("AMD", 10, "2026-01-02T14:30:00Z", "2026-01-02T14:34:00Z"),
        _trade("MSFT", 20, "2026-01-02T14:31:00Z", "2026-01-02T14:35:00Z"),
    ]
    baseline = trades if side == "baseline" else []
    ai = trades if side == "ai" else []
    with pytest.raises(ValueError, match="overlap"):
        compare_paper_strategies(baseline, ai, 1000)


def test_entry_at_previous_exit_is_permitted():
    trades = [
        _trade("AMD", 10, "2026-01-02T14:30:00Z", "2026-01-02T14:31:00Z"),
        _trade("MSFT", -2, "2026-01-02T09:31:00-05:00",
               "2026-01-02T14:32:00Z"),
    ]
    report = evaluate_closed_trades(trades, 1000)
    assert report["trade_count"] == 2
    assert report["net_pnl"] == 8


def test_nonoverlapping_trade_with_gap_is_permitted():
    trades = [
        _trade("AMD", 1, "2026-01-02T14:30:00Z", "2026-01-02T14:31:00Z"),
        _trade("MSFT", 2, "2026-01-02T14:35:00Z", "2026-01-02T14:36:00Z"),
    ]
    assert evaluate_closed_trades(trades, 1000)["net_pnl"] == 3
