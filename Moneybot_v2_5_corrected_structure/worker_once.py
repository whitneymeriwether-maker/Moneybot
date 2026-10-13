"""Single-run, broker-disconnected Moneybot paper worker for GitHub Actions.

This entry point never submits broker orders. It fails closed if a scheduled run
is too late or market data are stale. Enable scheduling only after validation.
"""
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from agent.engine import PaperEngine

ET = ZoneInfo('America/New_York')
LOG = logging.getLogger(__name__)


def eligible_time(now):
    local = now.astimezone(ET)
    return local.weekday() < 5 and '09:50' <= local.strftime('%H:%M') <= '15:59'


def recent_complete_bars(bars, now, max_age_minutes=12):
    """Only completed five-minute candles, with latest candle reasonably fresh."""
    if bars.empty:
        return bars
    if bars.index.tz is None:
        raise ValueError('Timezone-aware bar timestamps required')
    local_now = now.astimezone(ET)
    completed = bars[bars.index + pd.Timedelta(minutes=5) <= local_now - timedelta(seconds=30)]
    if completed.empty:
        return completed
    age = local_now - (completed.index.max() + pd.Timedelta(minutes=5))
    if age < timedelta(0) or age > timedelta(minutes=max_age_minutes):
        raise RuntimeError('Market data are stale; refusing to simulate trades')
    return completed


def run_once(now=None, symbols=None, fetch=None, engine=None):
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        raise ValueError('Worker clock must be timezone-aware')
    if not eligible_time(now):
        LOG.info('Outside regular market monitoring window; skipping')
        return 0
    if engine is None:
        url = os.environ.get('DATABASE_URL')
        if not url:
            raise RuntimeError('DATABASE_URL required: never use ephemeral SQLite in cloud worker')
        if not os.environ.get('APCA_API_KEY_ID') or not os.environ.get('APCA_API_SECRET_KEY'):
            raise RuntimeError('Missing Alpaca market-data credentials')
        engine = PaperEngine(database_url=url)
    if fetch is None:
        from agent.data import get_recent_bars
        fetch = get_recent_bars
    symbols = symbols if symbols is not None else [s.strip().upper() for s in os.getenv('WATCHLIST', 'AAPL,MSFT,NVDA,AMD,PLTR').split(',') if s.strip()]
    if not symbols:
        raise RuntimeError('WATCHLIST is empty')
    completed_count = 0
    failures = []
    for symbol in symbols:
        try:
            bars = fetch(symbol, now - timedelta(days=5), now)
            bars = recent_complete_bars(bars, now)
            if bars.empty:
                continue
            # First observation is a checkpoint, not a simulated historical trade.
            if engine.bootstrap(symbol, bars):
                LOG.info('Initialized %s checkpoint', symbol)
            else:
                engine.process(symbol, bars)
            completed_count += 1
        except Exception as exc:
            LOG.exception('Failed to process %s', symbol)
            failures.append(symbol)
    if failures:
        raise RuntimeError('One or more symbols failed: ' + ','.join(failures))
    return completed_count


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    count = run_once()
    LOG.info('Completed %d symbols', count)
