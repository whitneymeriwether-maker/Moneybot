"""Paper-only polling worker; never submits Alpaca orders."""
import os
import time
import logging
from datetime import datetime, timedelta
import pandas as pd
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from agent.data import get_recent_bars
from agent.engine import PaperEngine

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
ET = ZoneInfo('America/New_York')
SYMBOLS = [s.strip().upper() for s in os.getenv('WATCHLIST','AAPL,MSFT,NVDA,AMD,PLTR,SOFI,TSLA,AMZN,META,HOOD').split(',') if s.strip()]
engine = PaperEngine(os.getenv('DB_PATH','data/moneybot.sqlite3'), database_url=os.getenv('DATABASE_URL'))

def run_once(now=None):
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        raise ValueError('Worker clock must be timezone-aware')
    if now.weekday() >= 5 or not ('09:50' <= now.strftime('%H:%M') <= '16:15'):
        return
    for symbol in SYMBOLS:
        try:
            # Fetch enough context for indicators and recovery after short outages.
            bars = get_recent_bars(symbol, now-timedelta(days=5), now)
            # Alpaca timestamps denote bar START; exclude currently forming bar.
            bars = bars[bars.index + pd.Timedelta(minutes=5) <= now - timedelta(seconds=30)]
            if bars.empty:
                continue
            # Fresh worker starts from the latest completed bar; never invent
            # fills on historical candles fetched during startup.
            if engine.bootstrap(symbol, bars):
                logging.info('Initialized %s at %s; historical bars skipped', symbol, bars.index.max())
                continue
            engine.process(symbol, bars)
        except Exception:
            logging.exception('Error processing %s', symbol)

if __name__ == '__main__':
    if not os.getenv('APCA_API_KEY_ID') or not os.getenv('APCA_API_SECRET_KEY'):
        raise SystemExit('Missing Alpaca market-data credentials')
    logging.info('Moneybot PAPER-ONLY worker started; symbols=%s', SYMBOLS)
    while True:
        run_once()
        time.sleep(300)
