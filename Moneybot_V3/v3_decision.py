"""V3 research-only paper decision gate. No broker imports or network access."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
import re
from typing import Literal

Action = Literal['BUY', 'WAIT', 'REJECT']
_SYMBOL = re.compile(r'[A-Z][A-Z0-9.-]{0,9}')

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



def _finite_number(value):
    """Reject booleans, non-finite numbers, and oversized integers."""
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except (OverflowError, ValueError):
        return False


def _valid_policy(policy):
    """Fail closed on nonsensical paper-risk settings."""
    if not isinstance(policy, RiskPolicy):
        return False
    fractions = (
        policy.risk_per_trade, policy.daily_loss_limit, policy.max_exposure,
        policy.max_drawdown, policy.overnight_exposure,
    )
    return (
        all(_finite_number(value) and 0 < value <= 1 for value in fractions)
        and policy.overnight_exposure <= policy.max_exposure
        and type(policy.max_holding_sessions) is int
        and policy.max_holding_sessions >= 1
        and type(policy.max_data_age_seconds) is int
        and 0 <= policy.max_data_age_seconds <= 86400
    )


def _valid_evidence(evidence_ids):
    return (
        isinstance(evidence_ids, tuple)
        and bool(evidence_ids)
        and all(isinstance(item, str) and bool(item.strip()) for item in evidence_ids)
    )

def validate_paper_entry(candidate: Candidate, proposal: AIProposal,
                         account: PaperAccount, policy: RiskPolicy = RiskPolicy()) -> Decision:
    """Advisory gate only; real paper engine must recheck atomically before a fill."""
    if not _valid_policy(policy):
        return Decision(False, 'Invalid risk policy')
    if not isinstance(candidate, Candidate) or not isinstance(proposal, AIProposal) or not isinstance(account, PaperAccount):
        return Decision(False, 'Invalid paper decision input')
    if not isinstance(candidate.timestamp, datetime) or candidate.timestamp.tzinfo is None or candidate.timestamp.utcoffset() is None:
        return Decision(False, 'Timezone-aware timestamp required')
    if type(candidate.symbol) is not str or not _SYMBOL.fullmatch(candidate.symbol):
        return Decision(False, 'Invalid symbol')
    if type(candidate.data_age_seconds) is not int or not 0 <= candidate.data_age_seconds <= policy.max_data_age_seconds:
        return Decision(False, 'Stale or future market data')
    # A self-reported age alone cannot prove freshness. Independently check
    # the source timestamp against the current UTC clock; tolerate at most
    # five seconds of future skew. This is a paper advisory check, not
    # evidence of source authenticity or an execution-time guarantee.
    now = datetime.now(timezone.utc)
    actual_age = now - candidate.timestamp
    if not timedelta(seconds=-5) <= actual_age <= timedelta(seconds=policy.max_data_age_seconds):
        return Decision(False, 'Stale or future market timestamp')
    values = (candidate.price, candidate.atr, candidate.relative_volume, proposal.confidence,
              account.cash, account.equity, account.current_exposure,
              account.realized_pnl_today, account.starting_equity, account.peak_equity)
    if not all(_finite_number(v) for v in values) or candidate.price <= 0 or candidate.atr <= 0:
        return Decision(False, 'Invalid numerical input')
    if candidate.atr >= candidate.price:
        return Decision(False, 'Stop would be non-positive')
    if not (candidate.opening_range_breakout is True and candidate.above_vwap is True and
            candidate.relative_volume >= 1.5 and candidate.ema9_above_ema20 is True):
        return Decision(False, 'Opening-range breakout criteria not satisfied')
    if proposal.action != 'BUY':
        return Decision(False, f'AI decision: {proposal.action}')
    if not isinstance(proposal.thesis, str) or not proposal.thesis.strip() or not isinstance(proposal.risks, str) or not proposal.risks.strip() or not _valid_evidence(proposal.evidence_ids):
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
    risk_budget = account.equity * policy.risk_per_trade
    exposure_limit = account.equity * policy.max_exposure
    headroom = max(0.0, exposure_limit - account.current_exposure)
    if not all(_finite_number(v) and v >= 0 for v in (
        distance, risk_budget, exposure_limit, headroom,
    )):
        return Decision(False, 'Non-finite paper sizing arithmetic')

    # Validate floating-point ratios before converting to whole shares.
    # Tiny prices or stop distances can overflow to infinity despite every
    # original market/account input being individually finite.
    share_limits = (
        risk_budget / distance,
        headroom / candidate.price,
        account.cash / candidate.price,
    )
    if not all(_finite_number(v) and v >= 0 for v in share_limits):
        return Decision(False, 'Non-finite paper sizing arithmetic')
    quantity = min(int(v) for v in share_limits)
    if quantity <= 0:
        return Decision(False, 'Insufficient risk budget, exposure headroom, or cash')

    stop = candidate.price - distance
    target = candidate.price + 2 * distance
    notional = quantity * candidate.price
    if (
        not all(_finite_number(v) and v > 0 for v in (stop, target, notional))
        or notional > account.cash
        or notional > headroom
    ):
        return Decision(False, 'Non-finite paper sizing arithmetic')
    return Decision(True, 'Approved for paper simulation only', quantity, stop, target)


def validate_overnight_hold(sessions_held: int, proposed_exposure: float,
                            account: PaperAccount, thesis: str,
                            evidence_ids: tuple[str, ...],
                            policy: RiskPolicy = RiskPolicy()) -> Decision:
    """Independent overnight gate. This does not implement end-of-day execution."""
    # A missing or malformed account state must never authorize an
    # overnight paper hold. Booleans are not monetary values.
    if not _valid_policy(policy):
        return Decision(False, 'Invalid risk policy')
    if not isinstance(account, PaperAccount):
        return Decision(False, 'Invalid paper account')
    if type(sessions_held) is not int or sessions_held < 1 or sessions_held >= policy.max_holding_sessions:
        return Decision(False, 'Maximum holding period reached')
    if not isinstance(thesis, str) or not thesis.strip() or not _valid_evidence(evidence_ids):
        return Decision(False, 'Overnight thesis and evidence required')
    # Apply the same account-integrity and daily-loss checks used for
    # entries. A hold must not bypass the paper account's risk stops.
    values = (
        proposed_exposure, account.cash, account.equity,
        account.current_exposure, account.realized_pnl_today,
        account.starting_equity, account.peak_equity,
    )
    if not all(_finite_number(value) for value in values):
        return Decision(False, 'Invalid exposure or equity')
    if (account.cash < 0 or account.equity <= 0
            or account.current_exposure < 0 or account.starting_equity <= 0
            or account.peak_equity <= 0 or account.peak_equity < account.equity
            or proposed_exposure <= 0):
        return Decision(False, 'Invalid exposure or equity')
    if account.equity <= account.peak_equity*(1-policy.max_drawdown):
        return Decision(False, 'Maximum portfolio drawdown reached')
    if account.realized_pnl_today <= -account.starting_equity*policy.daily_loss_limit:
        return Decision(False, 'Daily realized-loss circuit breaker')
    if account.current_exposure > account.equity*policy.max_exposure:
        return Decision(False, 'Maximum portfolio exposure exceeded')
    # An overnight hold must refer to an existing paper position. Never
    # authorize holding more notional than the account currently owns.
    # This is an advisory check; the paper engine must revalidate at close.
    if proposed_exposure > account.current_exposure:
        return Decision(False, 'Proposed hold exceeds existing paper exposure')
    if proposed_exposure > account.equity*policy.overnight_exposure:
        return Decision(False, 'Overnight exposure limit exceeded')
    return Decision(True, 'Eligible for paper overnight review only')
