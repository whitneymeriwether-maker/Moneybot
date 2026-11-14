"""Deterministic V3 market-analysis signal, strictly advisory.

No broker access, trading credentials, fill generation or side effects.
Observations must be independently authenticated and time-ordered by caller.
A HOLD is a valid outcome, not a failed trade.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def analyze_window(observations, *, symbol, now, max_age_seconds=90,
                   threshold_bps=20, min_observations=5):
    """Compare first/last validated mids; require a contiguous fresh window.

    This intentionally simple baseline is for paper research, not a claim of
    forecasting skill. Returns a candidate BUY/SELL/HOLD, never authorization.
    """
    if type(symbol) is not str or not symbol or type(observations) is not list:
        raise ValueError("Missing market observations")
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Aware current timestamp required")
    if type(min_observations) is not int or not 5 <= min_observations <= 100:
        raise ValueError("Invalid observation count policy")
    if type(threshold_bps) is not int or not 1 <= threshold_bps <= 1000:
        raise ValueError("Invalid signal threshold")
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 300:
        raise ValueError("Invalid freshness policy")
    if not min_observations <= len(observations) <= 100:
        raise ValueError("Insufficient or excessive market observations")
    previous = None
    prices = []
    for observation in observations:
        if type(observation) is not dict or observation.get("authenticated") is not True or observation.get("execution_authorized") is not False:
            raise ValueError("Unverified market observation")
        if observation.get("symbol") != symbol or observation.get("provider") not in ("alpaca", "polygon", "massive"):
            raise ValueError("Inconsistent market source")
        if observation.get("provider") != observations[0].get("provider"):
            raise ValueError("Mixed market providers")
        timestamp = observation.get("timestamp_utc")
        if type(timestamp) is not str:
            raise ValueError("Missing observation timestamp")
        try:
            stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Invalid observation timestamp") from None
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Unaware observation timestamp")
        stamp = stamp.astimezone(timezone.utc)
        if previous is not None and stamp <= previous:
            raise ValueError("Duplicate or out-of-order market observation")
        previous = stamp
        try:
            raw = observation.get("price")
            if type(raw) not in (str, Decimal):
                raise ValueError("Non-decimal price")
            price = Decimal(raw)
            if not price.is_finite() or price <= 0 or price != price.quantize(Decimal(".01")):
                raise ValueError("Invalid observation price")
        except (InvalidOperation, OverflowError):
            raise ValueError("Invalid observation price") from None
        prices.append(price)
    age = (now.astimezone(timezone.utc) - previous).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise ValueError("Latest observation stale or future-dated")
    # Do not accept a burst of identical-timestamp or near-identical ticks
    # as evidence of a time series.
    span = (previous - datetime.fromisoformat(observations[0]["timestamp_utc"].replace("Z", "+00:00")).astimezone(timezone.utc)).total_seconds()
    if span < 30 or span > 3600:
        raise ValueError("Observation window duration outside policy")
    change_bps = (prices[-1] / prices[0] - 1) * 10000
    signal = "BUY" if change_bps >= threshold_bps else "SELL" if change_bps <= -threshold_bps else "HOLD"
    return {"symbol": symbol, "signal": signal, "change_bps": str(change_bps.quantize(Decimal(".01"))),
            "observation_count": len(prices), "last_observed_utc": previous.isoformat(),
            "strategy": "simple_window_momentum_research_only", "candidate_only": True,
            "execution_authorized": False, "profitability_unverified": True}
