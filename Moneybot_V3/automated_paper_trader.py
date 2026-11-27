"""Run a single-symbol paper strategy against verified IEX observations.

Fills are modeled at the observed quote midpoint rounded to cents. Writes
are confined to the V3 paper schema in PostgreSQL.
"""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

try:
    from .alpaca_market_data import latest_alpaca_quote
    from .verified_market_quote import verified_quote
except ImportError:
    from alpaca_market_data import latest_alpaca_quote
    from verified_market_quote import verified_quote

SYMBOL = "SPY"
CYCLE_SECONDS = 300
MOMENTUM_THRESHOLD = Decimal("0.001")
MAX_ALLOCATION = Decimal("0.80")
DEFAULT_OPENING_CASH = Decimal("1000.00")
ZERO = Decimal("0.00")
CYCLE_COLUMNS = (
    "cycle_key, completed_at, symbol, quote_timestamp, provider, price, "
    "decision, cash, equity, net_deposits, realized_pnl, unrealized_pnl"
)


def _connect(dsn):
    import psycopg
    from psycopg.rows import dict_row

    if not dsn or not dsn.strip():
        raise ValueError("V3 paper database is not configured")
    return psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row)


def _lock(db):
    db.execute("SET LOCAL statement_timeout = '10s'")
    db.execute("SELECT pg_advisory_xact_lock(30271, 3)")


def initialize(dsn):
    """Install the idempotent V3 schema using the paper database owner."""
    schema = Path(__file__).with_name("postgres_paper_schema.sql").read_text()
    with _connect(dsn) as db:
        _lock(db)
        db.execute(schema)


def _time(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Paper trading requires timezone-aware times")
    return value.astimezone(timezone.utc)


def _balances(db):
    return db.execute("""
        SELECT (
            SELECT COALESCE(sum(CASE WHEN event_type = 'paper_deposit'
                                    THEN amount ELSE -amount END), 0)
            FROM moneybot_v3_paper.cash_events
        ) AS net_deposits,
        COALESCE(sum(CASE WHEN f.side = 'sell' THEN 1 ELSE -1 END
                     * f.shares * c.price), 0) AS proceeds,
        COALESCE(sum(f.realized_pnl), 0) AS realized_pnl
        FROM moneybot_v3_paper.automated_fills AS f
        JOIN moneybot_v3_paper.automated_cycles AS c USING (cycle_key)
    """).fetchone()


def _position(db):
    return db.execute("""
        SELECT shares, cost_basis FROM moneybot_v3_paper.automated_positions
        WHERE symbol = %s
    """, (SYMBOL,)).fetchone() or {"shares": 0, "cost_basis": ZERO}


def _decision(previous_price, price, shares, cash):
    if previous_price is None:
        return "warmup", 0
    momentum = price / previous_price - 1
    if shares and momentum <= -MOMENTUM_THRESHOLD:
        return "sell", shares
    if not shares and momentum >= MOMENTUM_THRESHOLD:
        quantity = int(cash * MAX_ALLOCATION // price)
        return ("buy", quantity) if quantity else ("insufficient_cash", 0)
    return "hold", 0


def run_cycle(dsn, *, session_open, session_close, now=None,
              opening_cash=DEFAULT_OPENING_CASH):
    """Record one actionable observation per five-minute exchange interval.

    The caller supplies the exchange calendar interval. Invalid observations
    and failures leave the interval available for retry.
    """
    start = _time(session_open)
    end = _time(session_close)
    current = _time(now) if now is not None else datetime.now(timezone.utc)
    if not start <= current < end:
        return None
    elapsed = int((current - start).total_seconds())
    interval_stamp = int(start.timestamp()) + elapsed // CYCLE_SECONDS * CYCLE_SECONDS
    key = f"spy:{interval_stamp}"
    with _connect(dsn) as db:
        existing = db.execute(
            "SELECT cycle_key FROM moneybot_v3_paper.automated_cycles WHERE cycle_key = %s",
            (key,),
        ).fetchone()
        if existing:
            return {"cycle_key": key, "status": "already_completed"}

    observation = latest_alpaca_quote(SYMBOL, now=now, round_for_paper=True)
    if observation["provider"] != "alpaca" or observation["feed"] != "iex":
        raise ValueError("Unexpected paper market-data feed")
    stamp = datetime.fromisoformat(observation["timestamp_utc"])
    quoted_at = _time(stamp)
    with _connect(dsn) as db:
        _lock(db)
        current = _time(now) if now is not None else datetime.now(timezone.utc)
        if not interval_stamp <= current.timestamp() < interval_stamp + CYCLE_SECONDS:
            return None
        if not start <= quoted_at <= current < end:
            raise ValueError("Quote and execution must belong to the current exchange session")
        verified = verified_quote(
            {"symbol": observation["symbol"], "timestamp": stamp, "price": observation["price"]},
            provider=observation["provider"], authenticated=observation["authenticated"],
            expected_symbol=SYMBOL, now=current,
        )
        price = Decimal(verified["price"])
        last_cycle = db.execute("""
            SELECT cycle_key, price, quote_timestamp, completed_at
            FROM moneybot_v3_paper.automated_cycles ORDER BY completed_at DESC LIMIT 1
        """).fetchone()
        if last_cycle and (
            last_cycle["cycle_key"] == key or last_cycle["quote_timestamp"] >= quoted_at
            or last_cycle["completed_at"].timestamp() >= interval_stamp
        ):
            return {"cycle_key": key, "status": "already_observed"}
        db.execute("LOCK TABLE moneybot_v3_paper.cash_events IN SHARE ROW EXCLUSIVE MODE")
        if opening_cash is not None:
            db.execute("""
                INSERT INTO moneybot_v3_paper.cash_events (event_id, event_type, amount, payload)
                SELECT 'automated-opening-cash', 'paper_deposit', %s,
                       '{"source":"automated_paper_trader"}'::jsonb
                WHERE NOT EXISTS (SELECT 1 FROM moneybot_v3_paper.cash_events)
                ON CONFLICT (event_id) DO NOTHING
            """, (opening_cash,))
        balances = _balances(db)
        cash = balances["net_deposits"] + balances["proceeds"]
        if cash < 0:
            raise ValueError("Paper account cash balance is negative")
        position = _position(db)
        shares = position["shares"]
        cost = position["cost_basis"]
        previous_price = last_cycle["price"] if last_cycle else None
        decision, quantity = _decision(previous_price, price, shares, cash)

        fill_pnl = ZERO
        amount = quantity * price
        if decision == "buy":
            cash -= amount
            cost = amount
            shares = quantity
            db.execute("""
                INSERT INTO moneybot_v3_paper.automated_positions (symbol, shares, cost_basis)
                VALUES (%s, %s, %s)
            """, (SYMBOL, shares, cost))
        elif decision == "sell":
            cash += amount
            fill_pnl = amount - cost
            shares, cost = 0, ZERO
            db.execute("DELETE FROM moneybot_v3_paper.automated_positions WHERE symbol = %s", (SYMBOL,))

        equity = cash + shares * price
        unrealized = shares * price - cost
        db.execute("""
            INSERT INTO moneybot_v3_paper.automated_cycles (
                cycle_key, completed_at, symbol, quote_timestamp, provider, price,
                decision, cash, equity, net_deposits, realized_pnl, unrealized_pnl
            )
            VALUES (%s, %s, %s, %s, 'alpaca', %s, %s, %s, %s, %s, %s, %s)
        """, (key, current, SYMBOL, quoted_at, price, decision, cash, equity,
              balances["net_deposits"], balances["realized_pnl"] + fill_pnl, unrealized))
        if quantity:
            db.execute("""
                INSERT INTO moneybot_v3_paper.automated_fills (cycle_key, side, shares, realized_pnl)
                VALUES (%s, %s, %s, %s)
            """, (key, decision, quantity, fill_pnl))
    return {"cycle_key": key, "status": "completed", "decision": decision}


def _json_row(row):
    return {
        name: format(value, ".2f") if isinstance(value, Decimal)
        else value.isoformat() if isinstance(value, datetime)
        else value
        for name, value in row.items()
    }


def read_trading_state(dsn):
    """Read a consistent account snapshot with recent fills and equity history."""
    with _connect(dsn) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        db.execute("SET LOCAL statement_timeout = '5s'")
        balances = _balances(db)
        position = _position(db)
        cycles = db.execute(f"""
            SELECT {CYCLE_COLUMNS}, equity - net_deposits AS total_pnl
            FROM moneybot_v3_paper.automated_cycles ORDER BY completed_at DESC LIMIT 100
        """).fetchall()
        trades = db.execute("""
            SELECT c.symbol, f.side, f.shares, c.price, f.shares * c.price AS amount, f.realized_pnl,
                   c.quote_timestamp, c.completed_at AS executed_at, c.cycle_key
            FROM moneybot_v3_paper.automated_fills AS f
            JOIN moneybot_v3_paper.automated_cycles AS c USING (cycle_key)
            ORDER BY c.completed_at DESC LIMIT 100
        """).fetchall()
    latest = cycles[0] if cycles else None
    cash = balances["net_deposits"] + balances["proceeds"]
    realized = balances["realized_pnl"]
    deposits = balances["net_deposits"]
    positions = []
    market_value = ZERO
    unrealized = ZERO
    if position["shares"]:
        market_value = latest["price"] * position["shares"]
        unrealized = market_value - position["cost_basis"]
        positions.append(_json_row({
            "symbol": SYMBOL, **position, "last_price": latest["price"],
            "market_value": market_value, "unrealized_pnl": unrealized,
        }))
    return {
        **_json_row({
            "cash": cash, "equity": cash + market_value,
            "realized_pnl": realized, "unrealized_pnl": unrealized,
            "total_pnl": realized + unrealized, "net_deposits": deposits,
            "total_return_percent": (realized + unrealized) * 100 / deposits if deposits > 0 else None,
        }),
        "positions": positions, "trades": [_json_row(trade) for trade in trades],
        "latest_cycle": _json_row(latest) if latest else None,
        "performance": [_json_row(cycle) for cycle in reversed(cycles)],
    }
