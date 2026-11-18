"""Read only the V3 cash schema; never initialize balances or submit orders."""
from datetime import datetime
from decimal import Decimal
from paper_snapshot import project_cash_events


def read_cash_events(dsn, *, connect=None):
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("V3 database not configured")
    if connect is None:
        import psycopg
        connect = psycopg.connect
    with connect(dsn, connect_timeout=5) as db:
        with db.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '5s'")
            cur.execute("""SELECT sequence, event_type, amount, recorded_at
                           FROM moneybot_v3_paper.cash_events
                           ORDER BY sequence LIMIT 100001""")
            rows = cur.fetchall()
    if len(rows) > 100000:
        raise ValueError("Cash history exceeds audit bound")
    events = []
    previous = 0
    for seq, kind, amount, stamp in rows:
        if type(seq) is not int or seq <= previous:
            raise ValueError("Invalid journal sequence")
        if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
            raise ValueError("Invalid cash amount")
        if not isinstance(stamp, datetime):
            raise ValueError("Invalid timestamp")
        events.append(dict(sequence=seq, event_type=kind, amount=str(amount),
                           recorded_at=stamp.isoformat()))
        previous = seq
    snapshot = project_cash_events(events)
    return snapshot, events
