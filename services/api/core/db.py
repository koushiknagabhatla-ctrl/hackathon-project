"""Database access for the Auralis data core. SQLite or PostgreSQL/PostGIS.

    DATABASE_URL set    -> PostgreSQL via psycopg v3, schema at db/postgres_schema.sql
    DATABASE_URL unset  -> SQLite (WAL), schema at schema.sql

# ponytail: two backends, one public surface. SQLite exists because the demo
# and the whole test suite must run with `pip install -r requirements.txt` and
# no server - that is ADR-0006's zero-install promise and 142 tests depend on
# it. PostgreSQL exists because RLS, PITR and a GIST index are compliance and
# scale requirements SQLite cannot meet - ADR-0021. What collapses this to one
# backend: a committed Postgres (or pglite/embedded) fixture that CI and a
# laptop can start in under a second. On that day delete the SQLite branch,
# schema.sql, and `_translate()`, and this module halves.

Everything dialect-specific lives in ONE place: `_translate()` plus the
`_PgConn` facade below. No call site knows which backend it is talking to.

ponytail: ONE module-level connection behind a re-entrant lock. Ceiling: a
single writer process - every write serialises on `_lock`, so throughput is
capped at one transaction at a time and a second uvicorn worker would not be
protected by it. Upgrade path on PostgreSQL is a real pool (psycopg_pool);
the lock is what SQLite needs, not what PostgreSQL needs.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

API_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = API_DIR / "schema.sql"
PG_SCHEMA_PATH = API_DIR / "db" / "postgres_schema.sql"
DEFAULT_PATH = Path(os.environ.get("AURALIS_DB", str(REPO_ROOT / "auralis.db"))).resolve()

_lock = threading.RLock()
_conn: Any = None
_depth = 0  # transaction nesting depth, guarded by _lock


def database_url() -> str | None:
    """The PostgreSQL DSN, or None for SQLite. Read from the environment every
    time so a test that sets or clears it does not need a module reload."""
    return os.environ.get("DATABASE_URL", "").strip() or None


def is_postgres() -> bool:
    """True when the LIVE connection is PostgreSQL (not merely configured)."""
    return isinstance(_conn, _PgConn)


# ------------------------------------------------------------------ time/ids
def now_iso() -> str:
    """UTC, ISO8601, second precision, always suffixed 'Z'."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    """Parse an ISO8601 stamp (with or without 'Z') as an aware UTC datetime."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_s(observed_at: str, at: str | None = None) -> int:
    ref = parse_iso(at) if at else datetime.now(UTC)
    return int((ref - parse_iso(observed_at)).total_seconds())


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def jload(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def jdump(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)


# ------------------------------------------------------- dialect translation
_INSERT_OR = re.compile(
    r"^\s*INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", re.I
)


def _placeholders(sql: str) -> str:
    """`?` -> `%s`, and every literal `%` doubled, in one string-literal-aware
    scan. A naive str.replace corrupts `strftime('%s', ...)` and any `LIKE '%x'`,
    which is why this walks the string instead: characters inside '...' or
    "..." are copied through untouched apart from the `%` escaping psycopg's
    own placeholder scanner requires."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:  # doubled = escaped quote
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1].replace("%", "%%"))
            i = j + 1
            continue
        out.append("%s" if ch == "?" else "%%" if ch == "%" else ch)
        i += 1
    return "".join(out)


def _upsert(sql: str) -> str:
    """SQLite `INSERT OR IGNORE/REPLACE` -> PostgreSQL `ON CONFLICT`.

    ponytail: the conflict target for OR REPLACE is the FIRST column, which is
    the primary key in every such statement in this repo. Ceiling: a table with
    a second unique constraint that the row also collides on raises instead of
    replacing. Upgrade path is to write the `ON CONFLICT (col) DO UPDATE` out at
    the call site - portable SQL both engines accept - as routers/emergency.py
    now does for registered_device.fcm_token.
    """
    m = _INSERT_OR.match(sql)
    if m is None:
        return sql
    verb, table = m.group(1).upper(), m.group(2)
    cols = [c.strip() for c in m.group(3).split(",") if c.strip()]
    head = f"{sql[: m.start(0)]}INSERT INTO {table}({', '.join(cols)})"
    body = head + sql[m.end(0) :]
    if verb == "IGNORE":
        return body + " ON CONFLICT DO NOTHING"
    sets = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols[1:])
    return body + f" ON CONFLICT ({cols[0]}) DO UPDATE SET {sets}"


def _translate(sql: str, has_params: bool) -> str:
    """The one and only place SQLite SQL becomes PostgreSQL SQL."""
    sql = _upsert(sql)
    return _placeholders(sql) if has_params else sql


# -------------------------------------------------------------- psycopg glue
class _Row(dict):
    """A row shaped like `sqlite3.Row`: mapping access AND positional access.

    `db.scalar()` and `core/audit.py` both index rows by position (`row[0]`),
    every other call site indexes by name, and several do `dict(row)`. A plain
    dict row factory breaks the first group; this covers all three.
    """

    __slots__ = ()

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor: Any) -> Any:
    names = [c.name for c in (cursor.description or ())]
    return lambda values: _Row(zip(names, values))


class _PgConn:
    """`sqlite3.Connection`-shaped facade over a psycopg connection.

    Only `execute`, `executescript` and `close` are used by this codebase; the
    facade exists so `_translate()` runs on EVERY statement, including the ones
    call sites issue directly against the connection object `tx()` yields.
    """

    def __init__(self, raw: Any) -> None:
        self.raw = raw

    def execute(self, sql: str, params: Any = ()) -> Any:
        params = tuple(params) if params else None
        cur = self.raw.cursor()
        cur.execute(_translate(sql, params is not None), params)
        return cur

    def executescript(self, script: str) -> None:
        self.raw.execute(script)  # DDL: no parameters, so no translation

    def close(self) -> None:
        self.raw.close()

    def cursor(self) -> Any:
        return self.raw.cursor()


def _register_adapters(conn: Any) -> None:
    """Make PostgreSQL answer in the shapes this codebase already speaks.

    Three registrations, each removing an entire class of call-site edits:

    * `timestamptz` -> the same 'YYYY-MM-DDTHH:MM:SSZ' string SQLite stores, so
      `age_s()`, `parse_iso()` and plain string comparison keep working.
    * `jsonb` -> raw JSON text, so `jload()`/`jdump()` stay the only JSON codec
      and `evidence.integrity_hash` keeps hashing the same bytes.
    * `int` -> untyped, so the 1/0 this SQLite-born code writes into columns
      that are `boolean` in PostgreSQL coerce exactly as a literal would.
    """
    try:
        psycopg_adapt = importlib.import_module("psycopg.adapt")
        Dumper = psycopg_adapt.Dumper
        Loader = psycopg_adapt.Loader
    except (ImportError, ModuleNotFoundError):
        return

    class _IsoTimestamptz(Loader):
        def load(self, data: Any) -> Any:
            s = bytes(data).decode()
            try:
                return iso(datetime.fromisoformat(s.replace(" ", "T", 1)))
            except ValueError:  # 'infinity' / '-infinity'
                return s

    class _JsonText(Loader):
        def load(self, data: Any) -> Any:
            return bytes(data).decode()

    class _UntypedInt(Dumper):
        oid = 0  # unknown: PostgreSQL infers from the target column
        def dump(self, obj: Any) -> bytes:
            return str(obj).encode()

    conn.adapters.register_loader("timestamptz", _IsoTimestamptz)
    conn.adapters.register_loader("timestamp", _IsoTimestamptz)
    conn.adapters.register_loader("jsonb", _JsonText)
    conn.adapters.register_loader("json", _JsonText)
    conn.adapters.register_dumper(int, _UntypedInt)


def _open_pg(url: str) -> _PgConn:
    try:
        psycopg = importlib.import_module("psycopg")
    except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover - deployment error
        raise RuntimeError(
            "DATABASE_URL is set but psycopg is not installed. "
            "pip install 'psycopg[binary]>=3.2'"
        ) from exc
    raw = psycopg.connect(url, autocommit=True, row_factory=_row_factory)
    _register_adapters(raw)
    # Supabase puts PostGIS in the `extensions` schema; the DDL is unqualified.
    raw.execute("SET search_path TO public, extensions")
    return _PgConn(raw)


def _ensure_pg_schema(c: _PgConn) -> None:
    """Apply postgres_schema.sql only when the database is empty, so a normal
    boot needs no DDL privilege. scripts/migrate_to_postgres.py is the path
    that deliberately (re)applies it."""
    if c.execute("SELECT to_regclass('public.tenant')").fetchone()[0] is None:
        c.executescript(PG_SCHEMA_PATH.read_text(encoding="utf-8"))


def set_tenant(tenant_id: str) -> None:
    """Bind the row-level-security session variable the tenant policies read.

    No-op on SQLite, which has no RLS - there tenant isolation is the required
    `tenant_id` argument on every `repo.py` list function, exactly as ADR-0006
    described. Session-scoped (not SET LOCAL) because this module holds one
    long-lived connection and a COMMIT would otherwise clear it.
    """
    if is_postgres():
        conn().execute("SELECT set_config('auralis.tenant_id', ?, false)", (tenant_id,))


# ------------------------------------------------------------- connection
def _open(path: str | Path) -> sqlite3.Connection:
    p = str(path)
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, check_same_thread=False, isolation_level=None)
    # `_Row`, not `sqlite3.Row`: the code is written against dict-shaped rows
    # (the psycopg path), and calls `row.get(...)` in several places.
    # `sqlite3.Row` has no `.get`, so those raised AttributeError on SQLite
    # only. `_Row` keeps name access, positional access and `dict(row)`.
    c.row_factory = lambda cur, row: _Row(
        zip([d[0] for d in cur.description], row)
    )
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db(path: str | Path | None = None) -> Any:
    """Open the configured database and apply its schema. Idempotent.

    `path` is the SQLite file. With DATABASE_URL set it is ignored: the DSN
    names the database and `postgres_schema.sql` is applied only if empty.
    """
    global _conn, _depth
    with _lock:
        if _conn is not None:
            _conn.close()
        # Any per-thread handle points at the old file.
        if hasattr(_thread_local, "conn"):
            try:
                _thread_local.conn.close()
            except Exception:
                pass
            _thread_local.conn = None
            _thread_local.path = None
        _depth = 0
        url = database_url()
        if url:
            _conn = _open_pg(url)
            _ensure_pg_schema(_conn)
            return _conn
        _conn = _open(path or DEFAULT_PATH)
        _conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _conn.execute("PRAGMA foreign_keys=ON")
        return _conn


# One SQLite connection per thread. Sharing a single handle across FastAPI's
# threadpool interleaved cursors between requests, which surfaced as auth
# lookups intermittently returning the wrong row or none at all.
_thread_local = threading.local()


def conn() -> Any:
    # Postgres pools internally; only SQLite needs per-thread handles.
    if _conn is not None and is_postgres():
        return _conn

    existing = getattr(_thread_local, "conn", None)
    if existing is not None:
        return existing

    with _lock:
        if _conn is None:
            init_db(None)
        if is_postgres():
            return _conn
        path = getattr(_thread_local, "path", None) or _current_sqlite_path()

    c = _open(path)
    _thread_local.conn = c
    _thread_local.path = path
    return c


def _current_sqlite_path() -> str:
    """The file the primary connection is attached to."""
    try:
        row = _conn.execute("PRAGMA database_list").fetchone()
        if row and row["file"]:
            return row["file"]
    except Exception:
        pass
    return str(DEFAULT_PATH)


def close_thread_conn() -> None:
    """Release this thread's handle. Called when a worker retires."""
    c = getattr(_thread_local, "conn", None)
    if c is not None:
        try:
            c.close()
        finally:
            _thread_local.conn = None


get_conn = conn  # lane B (policy.py, gateway.py) calls it under this name


@contextmanager
def tx():
    """Re-entrant write transaction. The outermost `with` owns commit/rollback,
    so a nested call (ingest -> audit.append) joins the caller's transaction."""
    global _depth
    with _lock:
        c = conn()
        outer = _depth == 0
        if outer:
            # SQLite takes the write lock up front; PostgreSQL has no equivalent
            # and does not need one - MVCC plus the module lock above.
            c.execute("BEGIN" if isinstance(c, _PgConn) else "BEGIN IMMEDIATE")
        _depth += 1
        try:
            yield c
        except BaseException:
            _depth -= 1
            if outer:
                c.execute("ROLLBACK")
            raise
        else:
            _depth -= 1
            if outer:
                c.execute("COMMIT")


# ------------------------------------------------------------------ queries
def q(sql: str, *args: Any) -> list[Any]:
    return conn().execute(sql, args).fetchall()


def q1(sql: str, *args: Any) -> Any:
    return conn().execute(sql, args).fetchone()


def scalar(sql: str, *args: Any, default: Any = None) -> Any:
    row = q1(sql, *args)
    return default if row is None else row[0]


def run(sql: str, *args: Any) -> Any:
    with tx() as c:
        return c.execute(sql, args)


def demo() -> None:
    """Self-check for `_translate()` - the only non-obvious logic in this file.
    Run: python -m services.api.core.db"""
    t = lambda s: _translate(s, True)  # noqa: E731
    assert t("SELECT * FROM t WHERE a=? AND b=?") == "SELECT * FROM t WHERE a=%s AND b=%s"
    # a `?` inside a string literal is data, not a placeholder
    assert t("SELECT ? WHERE s='is it? yes'") == "SELECT %s WHERE s='is it? yes'"
    # `%` inside a literal must survive psycopg's placeholder scan
    assert t("SELECT strftime('%s', at) FROM t WHERE id=?") == (
        "SELECT strftime('%%s', at) FROM t WHERE id=%s"
    )
    assert t("SELECT * FROM t WHERE n LIKE '%x%' AND id=?") == (
        "SELECT * FROM t WHERE n LIKE '%%x%%' AND id=%s"
    )
    assert t("SELECT json_extract(v,'$.subject') FROM e WHERE id=?") == (
        "SELECT json_extract(v,'$.subject') FROM e WHERE id=%s"
    )
    # doubled quote inside a literal does not end it
    assert t("SELECT 'it''s ?' , ?") == "SELECT 'it''s ?' , %s"
    assert _translate("INSERT OR IGNORE INTO t(a,b) VALUES(?,?)", True) == (
        "INSERT INTO t(a, b) VALUES(%s,%s) ON CONFLICT DO NOTHING"
    )
    assert _translate("INSERT OR REPLACE INTO t(id,a,b) VALUES(?,?,?)", True) == (
        "INSERT INTO t(id, a, b) VALUES(%s,%s,%s) "
        "ON CONFLICT (id) DO UPDATE SET a=EXCLUDED.a, b=EXCLUDED.b"
    )
    # no params: nothing is escaped, because psycopg does not scan the string
    assert _translate("SELECT strftime('%s', at) FROM t", False) == (
        "SELECT strftime('%s', at) FROM t"
    )
    r = _Row({"a": 1, "b": 2})
    assert r[0] == 1 and r["b"] == 2 and dict(r) == {"a": 1, "b": 2}
    print("db.demo: ok")


if __name__ == "__main__":
    demo()
