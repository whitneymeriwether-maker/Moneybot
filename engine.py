"""Deterministic, broker-disconnected paper execution on completed 5-minute bars."""
import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd
from agent.strategy import build_features, find_signal
from agent.neon import get_connection, initialize_schema

class PaperEngine:
    def __init__(self, path='data/moneybot.sqlite3', starting_cash=1000.0, risk_pct=.005, daily_stop=.015, exposure_pct=.25, database_url=None):
        self.database_url = database_url
        self.path = Path(path)
        if not database_url:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.starting_cash = starting_cash
        self.risk_pct, self.daily_stop, self.exposure_pct = risk_pct, daily_stop, exposure_pct
        with self.db() as db:
            if self.database_url:
                initialize_schema(db)
                db.execute("INSERT INTO metadata(key,value) VALUES('cash',%s) ON CONFLICT(key) DO NOTHING", (str(starting_cash),))
                db.execute("INSERT INTO metadata(key,value) VALUES('starting_cash',%s) ON CONFLICT(key) DO NOTHING", (str(starting_cash),))
            else:
                db.executescript('''CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, kind TEXT, price REAL, qty INTEGER, pnl REAL, note TEXT);
                CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, entry REAL, qty INTEGER, stop REAL, target REAL, entry_ts TEXT);
                CREATE TABLE IF NOT EXISTS processed (symbol TEXT PRIMARY KEY, ts TEXT);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);''')
                db.execute("INSERT OR IGNORE INTO metadata VALUES ('cash', ?)", (str(starting_cash),))
                db.execute("INSERT OR IGNORE INTO metadata VALUES ('starting_cash', ?)", (str(starting_cash),))

    def db(self):
        return _PostgresCompat(get_connection(self.database_url)) if self.database_url else sqlite3.connect(self.path)

    def snapshot(self):
        with self.db() as db:
            cash = float(db.execute("SELECT value FROM metadata WHERE key='cash'").fetchone()[0])
            positions = db.execute('SELECT symbol,entry,qty,stop,target,entry_ts FROM positions').fetchall()
            if self.database_url:
                cursor = db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 250')
                events = pd.DataFrame(cursor.fetchall(), columns=[col.name for col in cursor.description])
            else:
                events = pd.read_sql_query('SELECT * FROM events ORDER BY id DESC LIMIT 250', db)
        return cash, positions, events

    def bootstrap(self, symbol, bars):
        """On first live startup, mark old bars processed without simulating past trades.

        Returns True if the symbol was initialized, False if already initialized.
        Use only in the live worker, not in historical research/backtests.
        """
        if bars.empty:
            return False
        ts = bars.index.max().isoformat()
        with self.db() as db:
            if self.database_url:
                db.execute("SELECT value FROM metadata WHERE key='cash' FOR UPDATE")
            else:
                db.execute('BEGIN IMMEDIATE')
            cur = db.execute('INSERT INTO processed(symbol,ts) VALUES(?,?) ON CONFLICT(symbol) DO NOTHING' if self.database_url else 'INSERT OR IGNORE INTO processed(symbol,ts) VALUES(?,?)', (symbol, ts))
            return cur.rowcount == 1

    def process(self, symbol, bars):
        """Bars must contain only fully completed candles. Replay is idempotent per symbol."""
        if bars.empty: return
        if bars.index.has_duplicates:
            raise ValueError('Duplicate bar timestamps are not permitted')
        if bars.index.tz is None:
            raise ValueError('Bars must have timezone-aware timestamps')
        if not bars.index.is_monotonic_increasing:
            raise ValueError('Bars must be sorted chronologically')
        df = build_features(bars)
        with self.db() as db:
            # Serialize all account mutations across symbols and worker instances.
            # PostgreSQL row locks persist until the transaction commits.
            # SQLite BEGIN IMMEDIATE obtains a writer lock before reading cash.
            if self.database_url:
                db.execute("SELECT value FROM metadata WHERE key='cash' FOR UPDATE")
            else:
                db.execute('BEGIN IMMEDIATE')
            last = db.execute('SELECT ts FROM processed WHERE symbol=?', (symbol,)).fetchone()
            for i in range(1, len(df)):
                ts = df.index[i].isoformat()
                if last and ts <= last[0]: continue
                prev, bar = df.iloc[i-1], df.iloc[i]
                day = str(bar['session_date'])
                cash = float(db.execute("SELECT value FROM metadata WHERE key='cash'").fetchone()[0])
                pos = db.execute('SELECT entry,qty,stop,target,entry_ts FROM positions WHERE symbol=?', (symbol,)).fetchone()
                if pos:
                    entry, qty, stop, target, entry_ts = pos
                    exit_price, reason = None, None
                    if str(prev['session_date']) != day:
                        # Missing end-of-day bars: mark the prior close as an approximate exit.
                        exit_price, reason = float(prev['close']), 'overnight_data_gap'
                    elif float(bar['open']) <= stop:
                        exit_price, reason = float(bar['open']), 'gap_stop'
                    elif float(bar['open']) >= target:
                        exit_price, reason = float(bar['open']), 'gap_target'
                    elif float(bar['low']) <= stop:
                        exit_price, reason = stop, 'stop'
                    elif float(bar['high']) >= target:
                        exit_price, reason = target, 'target'
                    elif str(bar['clock']) >= '15:55':
                        exit_price, reason = float(bar['close']), 'end_of_day'
                    if exit_price is not None:
                        pnl = (exit_price-entry)*qty
                        cash += exit_price*qty
                        db.execute("UPDATE metadata SET value=? WHERE key='cash'", (str(cash),))
                        db.execute('DELETE FROM positions WHERE symbol=?', (symbol,))
                        db.execute('INSERT INTO events(ts,symbol,kind,price,qty,pnl,note) VALUES(?,?,?,?,?,?,?)', (ts,symbol,'EXIT',exit_price,qty,pnl,reason))
                # One entry per symbol per day; only after previous bar closes.
                if str(prev['session_date']) == day and '09:50' <= str(bar['clock']) < '15:50':
                    already = db.execute("SELECT 1 FROM events WHERE symbol=? AND kind='ENTRY' AND substr(ts,1,10)=? LIMIT 1", (symbol,day)).fetchone()
                    if not already and not db.execute('SELECT 1 FROM positions WHERE symbol=?', (symbol,)).fetchone():
                        # Realized loss circuit breaker; portfolio-wide, resets each ET session.
                        realized = db.execute("SELECT COALESCE(SUM(pnl),0) FROM events WHERE kind='EXIT' AND substr(ts,1,10)=?", (day,)).fetchone()[0]
                        baseline = float(db.execute("SELECT value FROM metadata WHERE key='starting_cash'").fetchone()[0])
                        if realized > -baseline*self.daily_stop and find_signal(df.iloc[:i]).get('decision') == 'WATCH':
                            price = float(bar['open'])
                            atr = float(prev['atr14'])
                            distance = max(atr, price*.002)
                            held = db.execute('SELECT COALESCE(SUM(entry*qty),0) FROM positions').fetchone()[0]
                            equity_approx = cash + held
                            qty = min(int(equity_approx*self.risk_pct/distance), int(max(0,equity_approx*self.exposure_pct-held)/price), int(cash/price))
                            if qty > 0:
                                cash -= qty*price
                                db.execute("UPDATE metadata SET value=? WHERE key='cash'", (str(cash),))
                                db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?)', (symbol,price,qty,price-distance,price+2*distance,ts))
                                db.execute('INSERT INTO events(ts,symbol,kind,price,qty,pnl,note) VALUES(?,?,?,?,?,?,?)', (ts,symbol,'ENTRY',price,qty,None,'next_bar_open'))
                db.execute('INSERT INTO processed(symbol,ts) VALUES(?,?) ON CONFLICT(symbol) DO UPDATE SET ts=excluded.ts', (symbol,ts))


class _PostgresCompat:
    """Minimal qmark adapter; all statements are fixed application SQL, never user input."""
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)

    def execute(self, statement, params=None):
        # No literal question marks occur in Moneybot's fixed SQL statements.
        return self.connection.execute(statement.replace('?', '%s'), params)
