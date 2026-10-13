import pytest
from agent.neon import get_connection, initialize_schema, SCHEMA

def test_requires_database_url(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        get_connection()

def test_rejects_non_postgres_url():
    with pytest.raises(ValueError, match='PostgreSQL'):
        get_connection('sqlite:///test.db')

def test_schema_has_required_tables():
    for table in ('events', 'positions', 'processed', 'metadata'):
        assert f'CREATE TABLE IF NOT EXISTS {table}' in SCHEMA
