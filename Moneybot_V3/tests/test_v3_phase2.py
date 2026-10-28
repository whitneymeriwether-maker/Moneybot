import pytest
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from v3_decision import Candidate, AIProposal, PaperAccount, RiskPolicy, validate_paper_entry, validate_overnight_hold
from v3_evaluation import ClosedTrade, evaluate_closed_trades, compare_paper_strategies

C = Candidate('AMD', datetime.now(timezone.utc), 100, True, True, 2, True, 1, 60)
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
    account = replace(A, current_exposure=300)
    assert validate_overnight_hold(1, 200, account, 'Verified catalyst', ('filing:123',)).approved
    assert not validate_overnight_hold(1, 300, account, 'Verified catalyst', ('filing:123',)).approved
    assert not validate_overnight_hold(1, 200, account, '', ('filing:123',)).approved


@pytest.mark.parametrize('existing,proposed', [(0, 200), (150, 200)])
def test_overnight_rejects_hold_without_existing_paper_exposure(existing, proposed):
    account = replace(A, current_exposure=existing)
    decision = validate_overnight_hold(1, proposed, account, 'Thesis', ('sec:123',))
    assert not decision.approved
    assert decision.reason == 'Proposed hold exceeds existing paper exposure'

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
    t = [ClosedTrade('AMD', 10, '2026-01-02T14:30:00Z', '2026-01-02T14:31:00Z'), ClosedTrade('AMD', -5, '2026-01-02T14:32:00Z', '2026-01-02T14:33:00Z')]
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
    trades = [ClosedTrade('AMD', invalid, '2026-01-02T14:30:00Z', '2026-01-02T14:31:00Z')]
    with pytest.raises(ValueError, match='Trade PnL'):
        evaluate_closed_trades(trades, 1000)


def test_evaluator_rejects_cumulative_equity_overflow():
    trades = [ClosedTrade('AMD', 1e308, '2026-01-02T14:30:00Z', '2026-01-02T14:31:00Z')]
    with pytest.raises(ValueError, match='Non-finite cumulative equity'):
        evaluate_closed_trades(trades, 1e308)


def test_strategy_comparison_rejects_invalid_pnl():
    trades = [ClosedTrade('AMD', float('nan'), '2026-01-02T14:30:00Z', '2026-01-02T14:31:00Z')]
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


def test_evaluator_rejects_oversized_integers_without_crashing():
    huge = 10 ** 400
    with pytest.raises(ValueError, match='Starting capital'):
        evaluate_closed_trades([], huge)
    with pytest.raises(ValueError, match='Trade PnL'):
        evaluate_closed_trades([ClosedTrade('AMD', huge, '2026-01-02T14:30:00Z', '2026-01-02T14:31:00Z')], 1000)


def test_evaluator_rejects_nonfinite_gross_pnl_even_if_equity_is_finite():
    trades = [
        ClosedTrade('AMD', pnl, '2026-01-02T14:30:00Z',
                    f'2026-01-02T14:{31 + i:02d}:00Z')
        for i, pnl in enumerate(
            pnl for _ in range(5) for pnl in (4e307, -4e307)
        )
    ]
    with pytest.raises(ValueError, match='Non-finite aggregate PnL'):
        evaluate_closed_trades(trades, 1e308)


def test_entry_rejects_overflowed_share_ratios_without_crashing():
    # All inputs are finite, but risk_budget / stop_distance is infinite.
    candidate = replace(C, price=1e-320, atr=5e-321)
    decision = validate_paper_entry(candidate, P, A)
    assert not decision.approved
    assert decision.reason == 'Non-finite paper sizing arithmetic'


def test_entry_rejects_overflowed_target_without_approval():
    # Position sizing permits one share, but the 2R target is infinite.
    candidate = replace(C, price=8e307, atr=7e307)
    account = PaperAccount(
        cash=1.6e308, equity=1.6e308, current_exposure=0,
        realized_pnl_today=0, starting_equity=1.6e308,
        peak_equity=1.6e308,
    )
    decision = validate_paper_entry(
        candidate, P, account, RiskPolicy(risk_per_trade=1),
    )
    assert not decision.approved
    assert decision.reason == 'Non-finite paper sizing arithmetic'


def test_evaluator_rejects_nonfinite_percentage_return():
    # Finite dollars can still yield an unrepresentable percentage.
    trades = [ClosedTrade('AMD', 1e100, '2026-01-02T14:30:00Z', '2026-01-02T14:31:00Z')]
    with pytest.raises(ValueError, match='Non-finite return percentage'):
        evaluate_closed_trades(trades, 1e-300)


def test_evaluator_rejects_nonfinite_closed_trade_drawdown():
    # An extreme loss against tiny starting equity must not report infinity.
    trades = [ClosedTrade('AMD', -1e100, '2026-01-02T14:30:00Z', '2026-01-02T14:31:00Z')]
    with pytest.raises(ValueError, match='Non-finite closed-trade drawdown'):
        evaluate_closed_trades(trades, 1e-300)



def test_entry_rejects_old_timestamp_despite_fresh_reported_age():
    stale = datetime.now(timezone.utc) - timedelta(minutes=13)
    decision = validate_paper_entry(
        replace(C, timestamp=stale, data_age_seconds=0), P, A
    )
    assert not decision.approved
    assert decision.reason == 'Stale or future market timestamp'


def test_entry_rejects_future_timestamp_beyond_clock_skew():
    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    decision = validate_paper_entry(replace(C, timestamp=future), P, A)
    assert not decision.approved
    assert decision.reason == 'Stale or future market timestamp'


def test_entry_accepts_equivalent_non_utc_timestamp():
    east = timezone(timedelta(hours=5, minutes=30))
    candidate = replace(C, timestamp=datetime.now(timezone.utc).astimezone(east))
    assert validate_paper_entry(candidate, P, A).approved


def test_entry_timestamp_freshness_respects_policy_age_limit():
    observed = datetime.now(timezone.utc) - timedelta(minutes=14)
    candidate = replace(C, timestamp=observed, data_age_seconds=14 * 60)
    assert not validate_paper_entry(candidate, P, A).approved
    extended = RiskPolicy(max_data_age_seconds=900)
    assert validate_paper_entry(candidate, P, A, extended).approved


@pytest.mark.parametrize('symbol', ['A1', 'BRK.B', 'RDS-A', 'SOFI'])
def test_entry_symbol_matches_research_and_paper_ledger_grammar(symbol):
    assert validate_paper_entry(replace(C, symbol=symbol), P, A).approved


@pytest.mark.parametrize('symbol', ['amd', 'A B', 'A/B', 'A_B', 'ABCDEFGHIJK', ' SPY', 'SPY '])
def test_entry_rejects_symbols_paper_ledger_cannot_record(symbol):
    decision = validate_paper_entry(replace(C, symbol=symbol), P, A)
    assert not decision.approved
    assert decision.reason == 'Invalid symbol'


@pytest.mark.parametrize('age_limit', [86401, 10 ** 400])
def test_market_data_age_policy_fails_closed_on_unbounded_duration(age_limit):
    policy = RiskPolicy(max_data_age_seconds=age_limit)
    assert validate_paper_entry(C, P, A, policy).reason == 'Invalid risk policy'
    assert validate_overnight_hold(
        1, 100, replace(A, current_exposure=100),
        'Verified catalyst', ('sec:123',), policy,
    ).reason == 'Invalid risk policy'


def test_market_data_age_policy_accepts_bounded_24h_limit():
    assert validate_paper_entry(
        C, P, A, RiskPolicy(max_data_age_seconds=86400)
    ).approved


def test_entry_rejects_underreported_age_within_freshness_window():
    # A quote ten minutes old is within the default 12-minute maximum,
    # but reporting zero seconds of age contradicts its source timestamp.
    observed = datetime.now(timezone.utc) - timedelta(minutes=10)
    decision = validate_paper_entry(
        replace(C, timestamp=observed, data_age_seconds=0), P, A
    )
    assert not decision.approved
    assert decision.reason == 'Reported market data age understates timestamp'


def test_entry_accepts_consistent_reported_age():
    observed = datetime.now(timezone.utc) - timedelta(minutes=10)
    decision = validate_paper_entry(
        replace(C, timestamp=observed, data_age_seconds=600), P, A
    )
    assert decision.approved


def test_entry_accepts_conservatively_overstated_age():
    # A caller may report older data, but not younger data.
    observed = datetime.now(timezone.utc) - timedelta(minutes=2)
    decision = validate_paper_entry(
        replace(C, timestamp=observed, data_age_seconds=600), P, A
    )
    assert decision.approved
