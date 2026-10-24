import pytest
from datetime import datetime, timezone
from dataclasses import replace
from v3_decision import Candidate, AIProposal, PaperAccount, RiskPolicy, validate_paper_entry, validate_overnight_hold
from v3_evaluation import ClosedTrade, evaluate_closed_trades, compare_paper_strategies

C = Candidate('AMD', datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc), 100, True, True, 2, True, 1, 60)
P = AIProposal('BUY', 'Breakout with documented catalyst', 'Gap and reversal risk', ('sec:123',), .7)
A = PaperAccount(1000, 1000, 0, 0)

def test_aggressive_default_limits():
    p = RiskPolicy()
    assert (p.risk_per_trade, p.daily_loss_limit, p.max_exposure, p.max_drawdown) == (.015, .03, .50, .10)

def test_position_sizing_uses_stricter_exposure_cap():
    d = validate_paper_entry(C, P, A)
    assert d.approved and d.quantity == 5

def test_risk_budget_can_be_binding():
    d = validate_paper_entry(replace(C, atr=10), P, A)
    assert d.approved and d.quantity == 1

def test_breakout_required():
    assert not validate_paper_entry(replace(C, above_vwap=False), P, A).approved

def test_daily_stop():
    assert not validate_paper_entry(C, P, replace(A, realized_pnl_today=-30)).approved

def test_drawdown_stop():
    assert not validate_paper_entry(C, P, replace(A, cash=900, equity=900)).approved

def test_stale_and_future_data():
    for age in (-1, 721):
        assert not validate_paper_entry(replace(C, data_age_seconds=age), P, A).approved

def test_missing_ai_evidence():
    assert not validate_paper_entry(C, replace(P, evidence_ids=()), A).approved

def test_nan_rejected():
    assert not validate_paper_entry(replace(C, atr=float('nan')), P, A).approved

def test_overnight_requires_evidence_and_caps_exposure():
    assert validate_overnight_hold(1, 200, A, 'Verified catalyst', ('filing:123',)).approved
    assert not validate_overnight_hold(1, 300, A, 'Verified catalyst', ('filing:123',)).approved
    assert not validate_overnight_hold(1, 200, A, '', ('filing:123',)).approved

def test_overnight_two_day_limit():
    assert not validate_overnight_hold(2, 100, A, 'Still strong', ('filing:123',)).approved

def test_evaluator_and_baseline():
    t = [ClosedTrade('AMD', 10, 'a', 'b'), ClosedTrade('AMD', -5, 'c', 'd')]
    r = evaluate_closed_trades(t, 1000)
    assert r['net_pnl'] == 5 and r['trade_count'] == 2 and r['win_rate_pct'] == 50
    assert compare_paper_strategies([], t, 1000)['ai_minus_baseline_pnl'] == 5

def test_empty_evaluation():
    assert evaluate_closed_trades([], 1000)['win_rate_pct'] is None


@pytest.mark.parametrize('invalid', [0, -1, float('nan'), float('inf'), float('-inf'), True, '1000'])
def test_evaluator_rejects_invalid_starting_capital(invalid):
    with pytest.raises(ValueError, match='Starting capital'):
        evaluate_closed_trades([], invalid)


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), float('-inf'), True, '10'])
def test_evaluator_rejects_invalid_trade_pnl(invalid):
    trades = [ClosedTrade('AMD', invalid, 'a', 'b')]
    with pytest.raises(ValueError, match='Trade PnL'):
        evaluate_closed_trades(trades, 1000)


def test_evaluator_rejects_cumulative_equity_overflow():
    trades = [ClosedTrade('AMD', 1e308, 'a', 'b')]
    with pytest.raises(ValueError, match='Non-finite cumulative equity'):
        evaluate_closed_trades(trades, 1e308)


def test_strategy_comparison_rejects_invalid_pnl():
    trades = [ClosedTrade('AMD', float('nan'), 'a', 'b')]
    with pytest.raises(ValueError, match='Trade PnL'):
        compare_paper_strategies([], trades, 1000)
