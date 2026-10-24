"""V3 research-only paper decision gate. No broker imports or network access."""
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Literal

Action = Literal['BUY', 'WAIT', 'REJECT']

@dataclass(frozen=True)
class RiskPolicy:
    risk_per_trade: float = .015
    daily_loss_limit: float = .03
    max_exposure: float = .50
    max_drawdown: float = .10
    overnight_exposure: float = .25
    max_holding_sessions: int = 2
    max_data_age_seconds: int = 720

@dataclass(frozen=True)
class Candidate:
    symbol: str
    timestamp: datetime
    price: float
    opening_range_breakout: bool
    above_vwap: bool
    relative_volume: float
    ema9_above_ema20: bool
    atr: float
    data_age_seconds: int

@dataclass(frozen=True)
class AIProposal:
    action: Action
    thesis: str
    risks: str
    evidence_ids: tuple[str, ...]
    confidence: float

@dataclass(frozen=True)
class PaperAccount:
    cash: float
    equity: float
    current_exposure: float
    realized_pnl_today: float
    starting_equity: float = 1000.0
    peak_equity: float = 1000.0

@dataclass(frozen=True)
class Decision:
    approved: bool
    reason: str
    quantity: int = 0
    stop: float = 0.0
    target: float = 0.0


def validate_paper_entry(candidate: Candidate, proposal: AIProposal,
                         account: PaperAccount, policy: RiskPolicy = RiskPolicy()) -> Decision:
    """Advisory gate only; real paper engine must recheck atomically before a fill."""
    if candidate.timestamp.tzinfo is None or candidate.timestamp.utcoffset() is None:
        return Decision(False, 'Timezone-aware timestamp required')
    if not candidate.symbol or not candidate.symbol.isascii() or not candidate.symbol.replace('.', '').isalpha():
        return Decision(False, 'Invalid symbol')
    if not 0 <= candidate.data_age_seconds <= policy.max_data_age_seconds:
        return Decision(False, 'Stale or future market data')
    values = (candidate.price, candidate.atr, candidate.relative_volume, proposal.confidence,
              account.cash, account.equity, account.current_exposure,
              account.realized_pnl_today, account.starting_equity, account.peak_equity)
    if not all(isfinite(v) for v in values) or candidate.price <= 0 or candidate.atr <= 0:
        return Decision(False, 'Invalid numerical input')
    if not (candidate.opening_range_breakout and candidate.above_vwap and
            candidate.relative_volume >= 1.5 and candidate.ema9_above_ema20):
        return Decision(False, 'Opening-range breakout criteria not satisfied')
    if proposal.action != 'BUY':
        return Decision(False, f'AI decision: {proposal.action}')
    if not proposal.thesis.strip() or not proposal.risks.strip() or not proposal.evidence_ids:
        return Decision(False, 'Missing auditable reasoning or evidence')
    if not 0 <= proposal.confidence <= 1:
        return Decision(False, 'Invalid confidence')
    if account.equity <= 0 or account.cash <= 0 or account.current_exposure < 0 or account.starting_equity <= 0 or account.peak_equity <= 0:
        return Decision(False, 'Invalid or depleted paper account')
    if account.peak_equity < account.equity:
        return Decision(False, 'Invalid peak equity state')
    if account.equity <= account.peak_equity * (1-policy.max_drawdown):
        return Decision(False, 'Maximum portfolio drawdown reached')
    if account.realized_pnl_today <= -account.starting_equity * policy.daily_loss_limit:
        return Decision(False, 'Daily realized-loss circuit breaker')
    distance = max(candidate.atr, candidate.price * .002)
    headroom = max(0.0, account.equity * policy.max_exposure - account.current_exposure)
    quantity = min(int(account.equity * policy.risk_per_trade / distance),
                   int(headroom / candidate.price), int(account.cash / candidate.price))
    if quantity <= 0:
        return Decision(False, 'Insufficient risk budget, exposure headroom, or cash')
    return Decision(True, 'Approved for paper simulation only', quantity,
                    candidate.price-distance, candidate.price+2*distance)


def validate_overnight_hold(sessions_held: int, proposed_exposure: float,
                            account: PaperAccount, thesis: str,
                            evidence_ids: tuple[str, ...],
                            policy: RiskPolicy = RiskPolicy()) -> Decision:
    """Independent overnight gate. This does not implement end-of-day execution."""
    # A missing or malformed account state must never authorize an
    # overnight paper hold. Booleans are not monetary values.
    if type(sessions_held) is not int or sessions_held < 1 or sessions_held >= policy.max_holding_sessions:
        return Decision(False, 'Maximum holding period reached')
    if not isinstance(thesis, str) or not thesis.strip() or not evidence_ids:
        return Decision(False, 'Overnight thesis and evidence required')
    values = (proposed_exposure, account.equity, account.peak_equity)
    if any(type(value) not in (int, float) or not isfinite(value) for value in values):
        return Decision(False, 'Invalid exposure or equity')
    if (account.equity <= 0 or account.peak_equity <= 0
            or account.peak_equity < account.equity or proposed_exposure < 0):
        return Decision(False, 'Invalid exposure or equity')
    if account.equity <= account.peak_equity*(1-policy.max_drawdown):
        return Decision(False, 'Maximum portfolio drawdown reached')
    if proposed_exposure > account.equity*policy.overnight_exposure:
        return Decision(False, 'Overnight exposure limit exceeded')
    return Decision(True, 'Eligible for paper overnight review only')
