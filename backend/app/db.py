"""Database access layer.

* SQLite (stdlib `sqlite3`) is the default and is the configuration exercised by
  the automated test suite.
* PostgreSQL is supported through `psycopg` (v3) when it is installed and
  DATABASE_URL starts with `postgresql://`. The PostgreSQL schema is verified to
  apply on PostgreSQL 16, but the runtime driver path was not exercised in the
  build environment (psycopg could not be installed offline). Treat it as
  experimental until the test suite has been run against it.

SQL in this code base uses `?` placeholders; they are translated for psycopg.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import clock

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    def __init__(self, url: str):
        self.url = url
        if url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            self.path = url[len("sqlite:///"):]
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        elif url.startswith(("postgresql://", "postgres://")):
            self.dialect = "postgres"
            self.path = None
        else:
            raise ValueError("DATABASE_URL must start with sqlite:/// or postgresql://")
        self._lock = threading.RLock()
        self._memory_conn: sqlite3.Connection | None = None

    # -- connections -----------------------------------------------------
    def _sqlite_connect(self) -> sqlite3.Connection:
        if self.path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA foreign_keys = ON")
            return self._memory_conn
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    @contextmanager
    def tx(self) -> Iterator["Tx"]:
        """A transaction. Commits on success, rolls back on exception."""
        if self.dialect == "sqlite":
            with self._lock:
                conn = self._sqlite_connect()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    yield Tx(conn, "sqlite")
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                finally:
                    if conn is not self._memory_conn:
                        conn.close()
        else:  # pragma: no cover - requires psycopg + a PostgreSQL server
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore

            with psycopg.connect(self.url, row_factory=dict_row) as conn:
                with conn.transaction():
                    yield Tx(conn, "postgres")

    def close(self) -> None:
        """Close the persistent in-memory connection (file databases open one connection per transaction)."""
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None

    # -- migrations ------------------------------------------------------
    def migrate(self) -> list[str]:
        applied: list[str] = []
        folder = MIGRATIONS_DIR / self.dialect
        with self.tx() as tx:
            tx.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {r["version"] for r in tx.all("SELECT version FROM schema_migrations")}
        for path in sorted(folder.glob("*.sql")):
            version = path.stem
            if version in done:
                continue
            with self.tx() as tx:
                tx.script(path.read_text(encoding="utf-8"))
                tx.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, clock.now_iso()))
            applied.append(version)
        return applied


_PLACEHOLDER = re.compile(r"\?")


class Tx:
    def __init__(self, conn: Any, dialect: str):
        self.conn = conn
        self.dialect = dialect

    def _sql(self, sql: str) -> str:
        return _PLACEHOLDER.sub("%s", sql) if self.dialect == "postgres" else sql

    def execute(self, sql: str, params: tuple | list = ()) -> Any:
        return self.conn.execute(self._sql(sql), tuple(params))

    def script(self, sql: str) -> None:
        if self.dialect == "sqlite":
            # executescript would COMMIT our transaction; run statements individually.
            for statement in _split_sql(sql):
                self.conn.execute(statement)
        else:  # pragma: no cover
            self.conn.execute(sql)

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        row = self.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def all(self, sql: str, params: tuple | list = ()) -> list[dict]:
        return [dict(r) for r in self.execute(sql, params).fetchall()]

    def scalar(self, sql: str, params: tuple | list = ()) -> Any:
        row = self.execute(sql, params).fetchone()
        if row is None:
            return None
        return row[0] if self.dialect == "sqlite" else next(iter(dict(row).values()))

    def insert(self, table: str, values: dict, returning: str | None = None) -> Any:
        cols = list(values.keys())
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        if returning:
            sql += f" RETURNING {returning}"
            return self.scalar(sql, [_encode(values[c]) for c in cols])
        self.execute(sql, [_encode(values[c]) for c in cols])
        return None

    def update(self, table: str, key: str, key_value: Any, values: dict) -> None:
        cols = list(values.keys())
        sql = f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in cols)} WHERE {key} = ?"
        self.execute(sql, [_encode(values[c]) for c in cols] + [key_value])


def _encode(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), sort_keys=True)
    if isinstance(v, bool):
        return int(v)
    return v


def _split_sql(sql: str) -> list[str]:
    """Split a migration file into statements, keeping trigger bodies intact."""
    statements: list[str] = []
    buf: list[str] = []
    in_trigger = False
    for line in sql.splitlines():
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            in_trigger = True
        if in_trigger:
            if upper.endswith("END;"):
                statements.append("\n".join(buf))
                buf, in_trigger = [], False
        elif stripped.endswith(";"):
            statements.append("\n".join(buf))
            buf = []
    if buf and "".join(buf).strip():
        statements.append("\n".join(buf))
    return statements


def loads(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)
