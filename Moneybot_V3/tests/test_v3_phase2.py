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

def test_overnight_daily_loss_circuit_breaker():
    account = replace(A, realized_pnl_today=-30)
    decision = validate_overnight_hold(1, 200, account, 'Thesis', ('sec:123',))
    assert not decision.approved
    assert decision.reason == 'Daily realized-loss circuit breaker'


@pytest.mark.parametrize('field,invalid', [
    ('cash', -1), ('cash', True), ('cash', float('nan')),
    ('current_exposure', -1), ('current_exposure', '100'),
    ('realized_pnl_today', float('inf')),
    ('starting_equity', 0), ('starting_equity', None),
    ('equity', '1000'),
])
def test_overnight_rejects_malformed_account_state(field, invalid):
    account = replace(A, **{field: invalid})
    decision = validate_overnight_hold(1, 200, account, 'Thesis', ('sec:123',))
    assert not decision.approved
    assert decision.reason == 'Invalid exposure or equity'


def test_overnight_rejects_zero_proposed_exposure():
    decision = validate_overnight_hold(1, 0, A, 'Thesis', ('sec:123',))
    assert not decision.approved
    assert decision.reason == 'Invalid exposure or equity'


def test_risk_gates_reject_oversized_integers_without_crashing():
    huge = 10 ** 400
    assert validate_paper_entry(replace(C, price=huge), P, A).reason == 'Invalid numerical input'
    assert validate_paper_entry(C, P, replace(A, cash=huge)).reason == 'Invalid numerical input'
    assert validate_paper_entry(C, P, A, RiskPolicy(max_exposure=huge)).reason == 'Invalid risk policy'
    assert validate_overnight_hold(
        1, huge, A, 'Thesis', ('sec:123',)
    ).reason == 'Invalid exposure or equity'
    assert validate_overnight_hold(
        1, 200, replace(A, peak_equity=huge), 'Thesis', ('sec:123',)
    ).reason == 'Invalid exposure or equity'


def test_overnight_rejects_existing_overexposure():
    account = replace(A, current_exposure=600)
    decision = validate_overnight_hold(1, 200, account, 'Thesis', ('sec:123',))
    assert not decision.approved
    assert decision.reason == 'Maximum portfolio exposure exceeded'


def test_overnight_accepts_zero_cash_with_valid_existing_hold():
    account = replace(A, cash=0, current_exposure=200)
    assert validate_overnight_hold(
        1, 200, account, 'Thesis', ('sec:123',)
    ).approved



@pytest.mark.parametrize('peak', [0, -100, 900, float('nan'), float('inf'), True])
def test_overnight_rejects_invalid_peak_equity(peak):
    account = replace(A, peak_equity=peak)
    decision = validate_overnight_hold(1, 200, account, 'Verified catalyst', ('filing:123',))
    assert not decision.approved
    assert decision.reason == 'Invalid exposure or equity'


@pytest.mark.parametrize('exposure', [True, -1, float('nan'), float('inf'), '200'])
def test_overnight_rejects_invalid_exposure(exposure):
    decision = validate_overnight_hold(1, exposure, A, 'Verified catalyst', ('filing:123',))
    assert not decision.approved
    assert decision.reason == 'Invalid exposure or equity'


@pytest.mark.parametrize('sessions', [True, 1.0, '1', 0, -1])
def test_overnight_requires_positive_integer_sessions(sessions):
    decision = validate_overnight_hold(sessions, 200, A, 'Verified catalyst', ('filing:123',))
    assert not decision.approved


def test_overnight_rejects_missing_thesis_type():
    decision = validate_overnight_hold(1, 200, A, None, ('filing:123',))
    assert not decision.approved
    assert decision.reason == 'Overnight thesis and evidence required'


def test_overnight_rejects_equity_above_recorded_peak():
    account = replace(A, equity=1100, peak_equity=1000)
    assert not validate_overnight_hold(
        1, 200, account, 'Verified catalyst', ('filing:123',)
    ).approved

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


@pytest.mark.parametrize('field,invalid', [
    ('price', True), ('price', '100'), ('atr', None),
    ('relative_volume', '2'), ('relative_volume', float('inf')),
])
def test_entry_rejects_malformed_market_numbers(field, invalid):
    decision = validate_paper_entry(replace(C, **{field: invalid}), P, A)
    assert not decision.approved
    assert decision.reason == 'Invalid numerical input'


@pytest.mark.parametrize('field,invalid', [
    ('cash', True), ('equity', '1000'), ('current_exposure', None),
    ('realized_pnl_today', float('nan')), ('peak_equity', float('inf')),
])
def test_entry_rejects_malformed_account_numbers(field, invalid):
    decision = validate_paper_entry(C, P, replace(A, **{field: invalid}))
    assert not decision.approved
    assert decision.reason == 'Invalid numerical input'


def test_entry_rejects_nonpositive_stop():
    decision = validate_paper_entry(replace(C, atr=100), P, A)
    assert not decision.approved
    assert decision.reason == 'Stop would be non-positive'


@pytest.mark.parametrize('invalid', [True, 60.0, None, '60'])
def test_entry_rejects_invalid_data_age_type(invalid):
    assert not validate_paper_entry(replace(C, data_age_seconds=invalid), P, A).approved


@pytest.mark.parametrize('invalid', [None, 12, ''])
def test_entry_rejects_invalid_symbol_type(invalid):
    assert not validate_paper_entry(replace(C, symbol=invalid), P, A).approved


def test_entry_rejects_invalid_timestamp_type():
    assert not validate_paper_entry(replace(C, timestamp='2026-10-14'), P, A).approved


@pytest.mark.parametrize('field', ['opening_range_breakout', 'above_vwap', 'ema9_above_ema20'])
def test_entry_requires_boolean_true_signals(field):
    assert not validate_paper_entry(replace(C, **{field: 1}), P, A).approved


@pytest.mark.parametrize('field,invalid', [
    ('thesis', None), ('risks', None), ('evidence_ids', ('',)),
    ('evidence_ids', (None,)), ('evidence_ids', 'source:123'),
])
def test_entry_rejects_malformed_reasoning(field, invalid):
    assert not validate_paper_entry(C, replace(P, **{field: invalid}), A).approved


@pytest.mark.parametrize('invalid', [True, None, '0.7'])
def test_entry_rejects_malformed_confidence(invalid):
    assert not validate_paper_entry(C, replace(P, confidence=invalid), A).approved


@pytest.mark.parametrize('policy', [
    RiskPolicy(risk_per_trade=float('inf')),
    RiskPolicy(max_exposure=1.5),
    RiskPolicy(overnight_exposure=.75),
    RiskPolicy(max_data_age_seconds=-1),
    RiskPolicy(max_holding_sessions=True),
])
def test_invalid_risk_policy_blocks_entry_and_overnight(policy):
    entry = validate_paper_entry(C, P, A, policy)
    hold = validate_overnight_hold(1, 100, A, 'Verified catalyst', ('sec:123',), policy)
    assert not entry.approved and entry.reason == 'Invalid risk policy'
    assert not hold.approved and hold.reason == 'Invalid risk policy'


@pytest.mark.parametrize('invalid', [(' ',), (None,), 'sec:123', []])
def test_overnight_rejects_malformed_evidence(invalid):
    assert not validate_overnight_hold(1, 100, A, 'Verified catalyst', invalid).approved


def test_malformed_paper_objects_fail_closed():
    assert not validate_paper_entry(None, P, A).approved
    assert not validate_paper_entry(C, None, A).approved
    assert not validate_paper_entry(C, P, None).approved
    assert not validate_overnight_hold(1, 100, None, 'Thesis', ('sec:123',)).approved
