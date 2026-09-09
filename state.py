"""Opening the one local database.

Everything this program writes — the cached corpus, the roadmaps, the cards,
what you have marked known — lives in a single SQLite file, and the web server
reads it from several threads while you click buttons that write to it.

SQLite's default journal makes that combination fail. A writer needs an
exclusive lock, any reader blocks it, and loading a page reads ninety
thousand sentences — far longer than the five seconds a writer waits before
giving up. Pressing "I know this" while a page was still loading returned
`database is locked`, as a 500.

Write-ahead logging is the fix: readers and one writer proceed at the same
time, each reader seeing the file as it was when its read began. The longer
busy timeout covers the remaining case, two writes at once, which is brief.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# Long enough to outlast any write this program makes, short enough that a
# genuine deadlock still surfaces rather than hanging the page forever.
BUSY_TIMEOUT_MS = 30_000


def open_state(path: Path) -> sqlite3.Connection:
    """A connection to the local state file, safe to use while others read."""
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    # Persistent once set, but re-issued because it costs nothing and a fresh
    # database file would otherwise keep the default until someone remembered.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
