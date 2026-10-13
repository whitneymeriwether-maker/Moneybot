from agent.engine import _PostgresCompat

class FakeConnection:
    def __init__(self):
        self.calls = []
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

def test_postgres_adapter_converts_bound_parameters():
    fake = FakeConnection()
    adapter = _PostgresCompat(fake)
    adapter.execute('SELECT * FROM positions WHERE symbol=? AND qty>?', ('AAPL', 0))
    assert fake.calls == [('SELECT * FROM positions WHERE symbol=%s AND qty>%s', ('AAPL', 0))]
