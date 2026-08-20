"""SQLite access for the Auralis data core.

ponytail: ONE module-level connection behind a re-entrant lock. Ceiling: a
single writer process — every write serialises on `_lock`, so throughput is
capped at one transaction at a time and a second uvicorn worker would not be
protected by it. Upgrade path: PostgreSQL + a real pool, reimplementing this
module and repo.py (schema.sql already names the same escape hatch).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

API_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = API_DIR / "schema.sql"
DEFAULT_PATH = API_DIR / "auralis.db"

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_depth = 0  # transaction nesting depth, guarded by _lock


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


# ------------------------------------------------------------- connection
def _open(path: str | Path) -> sqlite3.Connection:
    p = str(path)
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db(path: str | Path | None = None) -> sqlite3.Connection:
    """Open `path` and apply schema.sql. Idempotent (CREATE TABLE IF NOT EXISTS)."""
    global _conn, _depth
    with _lock:
        if _conn is not None:
            _conn.close()
        _depth = 0
        _conn = _open(path or DEFAULT_PATH)
        _conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _conn.execute("PRAGMA foreign_keys=ON")
        return _conn


def conn() -> sqlite3.Connection:
    with _lock:
        return _conn if _conn is not None else init_db(None)


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
            c.execute("BEGIN IMMEDIATE")
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
def q(sql: str, *args: Any) -> list[sqlite3.Row]:
    return conn().execute(sql, args).fetchall()


def q1(sql: str, *args: Any) -> sqlite3.Row | None:
    return conn().execute(sql, args).fetchone()


def scalar(sql: str, *args: Any, default: Any = None) -> Any:
    row = q1(sql, *args)
    return default if row is None else row[0]


def run(sql: str, *args: Any) -> sqlite3.Cursor:
    with tx() as c:
        return c.execute(sql, args)
