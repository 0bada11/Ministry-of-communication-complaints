"""SQLite access: connection handling, schema creation and seeding.

Uses the stdlib driver directly — the query surface is small enough that an ORM
would add more indirection than it removes.
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .domain import DEPARTMENTS

BASE_DIR = Path(__file__).resolve().parent.parent
# MOCT_DATA_DIR lets the test suite point at a throwaway directory.
DATA_DIR = Path(os.environ.get("MOCT_DATA_DIR") or BASE_DIR / "data")
DB_PATH = DATA_DIR / "complaints.db"
UPLOAD_DIR = DATA_DIR / "uploads"

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    code     TEXT NOT NULL UNIQUE,
    name_ar  TEXT NOT NULL,
    name_en  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS complaints (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_no   TEXT NOT NULL UNIQUE,
    citizen_name   TEXT NOT NULL,
    citizen_phone  TEXT NOT NULL,
    citizen_email  TEXT,
    governorate    TEXT,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    type           TEXT NOT NULL,
    priority       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'new',
    department_id  INTEGER REFERENCES departments(id),
    assignee       TEXT,
    resolution     TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    resolved_at    TEXT,
    closed_at      TEXT
);

CREATE TABLE IF NOT EXISTS attachments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id  INTEGER NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    stored_name   TEXT NOT NULL,
    content_type  TEXT,
    size          INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id  INTEGER NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
    action        TEXT NOT NULL,
    field         TEXT,
    old_value     TEXT,
    new_value     TEXT,
    note          TEXT,
    actor         TEXT NOT NULL DEFAULT 'system',
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_complaints_status     ON complaints(status);
CREATE INDEX IF NOT EXISTS idx_complaints_type       ON complaints(type);
CREATE INDEX IF NOT EXISTS idx_complaints_priority   ON complaints(priority);
CREATE INDEX IF NOT EXISTS idx_complaints_department ON complaints(department_id);
CREATE INDEX IF NOT EXISTS idx_complaints_created    ON complaints(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attachments_complaint ON attachments(complaint_id);
CREATE INDEX IF NOT EXISTS idx_events_complaint      ON events(complaint_id, id);
"""


def connect() -> sqlite3.Connection:
    # check_same_thread=False is required because FastAPI runs a sync
    # dependency's setup and its teardown on different threadpool threads.
    # Each request still gets its own connection and never shares it, so no
    # two threads touch one connection at the same time.
    #
    # isolation_level=None turns off the driver's implicit transactions so
    # get_db() can open them explicitly — see the BEGIN IMMEDIATE note below.
    conn = sqlite3.connect(
        DB_PATH, check_same_thread=False, timeout=10.0, isolation_level=None
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets readers work while a writer holds the lock.
    conn.execute("PRAGMA journal_mode = WAL")
    # Queue behind an active writer instead of failing straight away.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def get_db(write: bool = False) -> Iterator[sqlite3.Connection]:
    """One connection per request, committed on success.

    Writers open with BEGIN IMMEDIATE so the write lock is taken up front. A
    transaction that starts as a reader and only later tries to write gets
    SQLITE_BUSY the instant another writer is active — busy_timeout does not
    cover that upgrade, so two concurrent submissions would fail outright.
    Readers stay in autocommit and never block each other.
    """
    conn = connect()
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def db_dependency() -> Iterator[sqlite3.Connection]:
    """Read-only routes."""
    with get_db() as conn:
        yield conn


def write_db_dependency() -> Iterator[sqlite3.Connection]:
    """Routes that modify data."""
    with get_db(write=True) as conn:
        yield conn


def init_db() -> None:
    """Create the data directories, the schema, and seed the departments."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with get_db(write=True) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO departments (code, name_ar, name_en)"
            " VALUES (:code, :name_ar, :name_en)",
            DEPARTMENTS,
        )
