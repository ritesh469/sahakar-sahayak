"""S1: seed_db.py must use the .env database and never run the K8s demo migration (003)."""

from app.config import settings
from scripts import seed_db


class _FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql):
        self.executed.append(sql)

    def close(self):
        pass


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()

    def cursor(self):
        return self.cur

    def commit(self):
        pass


def test_database_url_comes_from_settings():
    assert seed_db.DATABASE_URL == settings.database_url


def test_run_migrations_skips_k8s_demo():
    conn = _FakeConn()
    seed_db.run_migrations(conn)
    sql = "\n".join(conn.cur.executed)
    assert "CREATE TABLE IF NOT EXISTS users" in sql
    assert "DROP TABLE" not in sql
