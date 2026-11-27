"""Run an automated paper cycle only during the current U.S. equity session."""

from datetime import datetime, timezone
from functools import lru_cache
import os
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")


@lru_cache(maxsize=1)
def _exchange_calendar():
    import exchange_calendars

    return exchange_calendars.get_calendar("XNYS")


def session_bounds(now):
    if now.utcoffset() is None:
        raise ValueError("The cycle clock must be timezone-aware")
    day = now.astimezone(NEW_YORK).date().isoformat()
    calendar = _exchange_calendar()
    if not calendar.is_session(day):
        return None
    opening = calendar.session_open(day).to_pydatetime()
    closing = calendar.session_close(day).to_pydatetime()
    if opening <= now < closing:
        return opening, closing
    return None


def run_scheduled_cycle():
    if os.environ.get("V3_PAPER_TRADING_ENABLED") != "1":
        raise RuntimeError("V3 automated paper trading is disabled")
    now = datetime.now(timezone.utc)
    session = session_bounds(now)
    if session is None:
        return {"status": "market_closed"}
    dsn = os.environ.get("MONEYBOT_V3_DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("V3 paper database is unavailable")

    from automated_paper_trader import run_cycle

    result = run_cycle(dsn, session_open=session[0], session_close=session[1])
    return result if result is not None else {"status": "interval_elapsed"}
