"""Read-only SQLite paper-ledger to AI advisory bridge for offline V3 research.

This module NEVER records a fill, sends an order, or contacts a provider.
The caller must independently verify marks, evidence, and risk history.
A successful decision is not execution authorization.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

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

    Cash, starting capital, equity, exposure and today's realized PnL
    are reconciled to the local ledger. The risk day is midnight-to-midnight
    America/New_York (including daylight-saving transitions). Peak equity
    remains caller-supplied and cannot be independently authenticated.
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
        # Reconstruct the New York trading-day realized PnL from SELL fills.
        # This rejects caller-supplied daily-loss figures that understate
        # recorded paper losses, without claiming market-data authenticity.
        ny_time = as_of.astimezone(ZoneInfo("America/New_York"))
        day_start = ny_time.replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).astimezone(timezone.utc)
        # A writer reservation prevents ordinary SQLite fill writers from
        # changing the ledger between the full replay audit and valuation.
        # Neither operation writes a fill. This is not an execution-time gate.
        with ledger.consistent_advisory_read():
            audit = ledger.audit_history(realized_since=day_start)
            snapshot = ledger.marked_snapshot(
                marks, as_of=as_of, max_age_seconds=policy.max_data_age_seconds,
            )
        # Account marks must be contemporaneous with the candidate signal.
        # A mark can satisfy the general freshness window yet predate the
        # signal by minutes, understating exposure or an intraday drawdown.
        # Permit only five seconds of cross-feed timestamp skew. Read the
        # canonical, ledger-validated marks rather than untrusted input.
        earliest_mark = candidate_utc - timedelta(seconds=5)
        if any(
            datetime.fromisoformat(position["mark_timestamp_utc"]) < earliest_mark
            for position in snapshot["positions"].values()
        ):
            return denied
        # Independently reject discrepancies even if a caller bypasses the
        # reservation or a storage anomaly yields inconsistent reads.
        if (
            audit["audited_fills"] != snapshot["fill_count"]
            or audit["cash"] != snapshot["cash"]
            or audit["realized_pnl"] != snapshot["realized_pnl"]
            or daily != Decimal(audit["realized_since"])
        ):
            return denied
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
