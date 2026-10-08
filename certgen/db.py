"""SQLite persistence helpers.

We use the standard-library ``sqlite3`` module on purpose: no ORM and no
database server to install, which keeps local setup simple on Windows.
"""
import os
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    event_name  TEXT NOT NULL,
    issued_on   TEXT NOT NULL,
    status      TEXT NOT NULL,
    total       INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL REFERENCES jobs(id),
    position         INTEGER NOT NULL,
    name             TEXT,
    email            TEXT,
    status           TEXT NOT NULL,
    error            TEXT,
    certificate_id   TEXT,
    certificate_path TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_job ON items(job_id);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)  # wait for locks instead of failing fast
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")  # better read/write concurrency
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def db_session(db_path: str):
    """Open a short-lived connection; commit on success, roll back on error.

    Each thread opens its own connection, so worker threads never share one.
    """
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
