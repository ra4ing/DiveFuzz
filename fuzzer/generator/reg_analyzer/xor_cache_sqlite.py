"""Exact, process-safe XOR history for the optional fast Spike backend.

The legacy implementation rereads a whole per-opcode text file for every
candidate and performs an unguarded read/append across worker processes.
This backend retains the same (opcode, decimal XOR value) uniqueness rule,
while SQLite's unique index makes the decision atomic and logarithmic in the
size of the corpus.  Legacy generation continues to use its original files.
"""
import os
import sqlite3
import threading
from pathlib import Path

_lock = threading.Lock()
_connections = {}  # (pid, absolute cache path) -> sqlite3.Connection

_SCHEMA = ("CREATE TABLE IF NOT EXISTS values_seen ("
           "opcode TEXT NOT NULL, xor_value TEXT NOT NULL, "
           "PRIMARY KEY (opcode, xor_value)) WITHOUT ROWID")


def prepare(cache_dir: Path) -> None:
    """Set WAL mode and create the schema before spawning any seed workers."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache_dir / "xor_values.sqlite3", timeout=60)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _connection(cache_dir: Path) -> sqlite3.Connection:
    path = (cache_dir / "xor_values.sqlite3").resolve()
    key = (os.getpid(), path)
    with _lock:
        conn = _connections.get(key)
        if conn is None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=60, isolation_level=None,
                                   check_same_thread=False)
            conn.execute("PRAGMA busy_timeout=60000")
            conn.execute("PRAGMA synchronous=NORMAL")
            _connections[key] = conn
        return conn


def check_and_add(cache_dir: Path, opcode: str, xor_value: int) -> bool:
    """Return True only for a first occurrence, even across parallel seeds."""
    conn = _connection(cache_dir)
    with _lock:
        cur = conn.execute("INSERT OR IGNORE INTO values_seen VALUES (?, ?)",
                           (opcode, str(xor_value)))
        return cur.rowcount == 1
