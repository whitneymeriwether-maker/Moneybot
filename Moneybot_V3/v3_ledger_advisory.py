"""Read-only SQLite paper-ledger to AI advisory bridge for offline V3 research.

This module NEVER records a fill, sends an order, or contacts a provider.
The caller must independently verify marks, evidence, and risk history.
A successful decision is not execution authorization.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from paper_ledger import MAX_CENTS, PaperLedger
from v3_decision import Candidate, Decision, PaperAccount, RiskPolicy, _valid_policy
from v3_research_advisory import ResearchReview, review_research_proposal


_CENT = Decimal("0.01")
_MAX_DOLLARS = Decimal(MAX_CENTS) / 100
_UNVERIFIED = "Unverified ledger snapshot or paper risk history"


def _risk_money(value, *, positive=False):
    """Require caller-supplied risk history to be exact decimal cents."""
    if type(value) not in (str, Decimal):
        raise ValueError("Risk history must use exact decimal money")
    try:
        number = Decimal(value)
        if (
            not number.is_finite()
            or abs(number) > _MAX_DOLLARS
            or (positive and number <= 0)
            or number != number.quantize(_CENT)
        ):
            raise ValueError("Invalid paper risk history")
        return number
    except (InvalidOperation, OverflowError):
        raise ValueError("Invalid paper risk history") from None


def review_ledger_research_proposal(
    payload: str,
    *,
    ledger: PaperLedger,
    marks: dict,
    as_of: datetime,
    peak_equity: str | Decimal,
    realized_pnl_today: str | Decimal,
    trusted_evidence_ids: tuple[str, ...],
    candidate: Candidate,
    policy: RiskPolicy = RiskPolicy(),
) -> ResearchReview:
    """Review AI JSON using a fresh, read-only marked SQLite paper account.

    Only cash, starting capital, current equity and exposure come from the
    local ledger. Peak equity and today's realized PnL are supplied by the
    caller because the ledger does not persist historical daily risk/marks.
    These two inputs are NOT independently authenticated by this adapter.
    Never use this advisory to execute or record a fill.
    """
    denied = ResearchReview(None, Decision(False, _UNVERIFIED))
    if (
        type(ledger) is not PaperLedger
        or not _valid_policy(policy)
        or not isinstance(candidate, Candidate)
        or not isinstance(as_of, datetime)
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
        or not isinstance(candidate.timestamp, datetime)
        or candidate.timestamp.tzinfo is None
        or candidate.timestamp.utcoffset() is None
    ):
        return denied

    # A historical marked snapshot must not masquerade as current risk state.
    # Permit at most five seconds of future clock skew, and never use an
    # account valuation that precedes the candidate market observation.
    now = datetime.now(timezone.utc)
    as_of_utc = as_of.astimezone(timezone.utc)
    candidate_utc = candidate.timestamp.astimezone(timezone.utc)
    if (
        not timedelta(seconds=-5)
        <= now - as_of_utc
        <= timedelta(seconds=policy.max_data_age_seconds)
        or candidate_utc > as_of_utc
    ):
        return denied

    try:
        peak = _risk_money(peak_equity, positive=True)
        daily = _risk_money(realized_pnl_today)
        snapshot = ledger.marked_snapshot(
            marks, as_of=as_of, max_age_seconds=policy.max_data_age_seconds,
        )
        start = Decimal(snapshot["starting_cash"])
        equity = Decimal(snapshot["equity"])
        cash = Decimal(snapshot["cash"])
        exposure = Decimal(snapshot["market_value"])
        # This independent equality check makes the provenance of the
        # advisory's equity/exposure explicit, rather than trusting a
        # separately fabricated PaperAccount.
        if (
            peak < start
            or peak < equity
            or cash + exposure != equity
            or equity <= 0
        ):
            return denied
        account = PaperAccount(
            cash=float(cash),
            equity=float(equity),
            current_exposure=float(exposure),
            realized_pnl_today=float(daily),
            starting_equity=float(start),
            peak_equity=float(peak),
        )
    except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError, sqlite3.DatabaseError):
        return denied

    return review_research_proposal(
        payload,
        trusted_evidence_ids=trusted_evidence_ids,
        candidate=candidate,
        account=account,
        policy=policy,
    )
