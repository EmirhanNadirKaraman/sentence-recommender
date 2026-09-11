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

# Settings for the size this file actually is. SQLite's defaults suit a small
# database; this one is a third of a gigabyte and is read far more than it is
# written.
#
# `cache_size` is negative to mean kibibytes rather than pages, so this is
# 256 MB rather than the default two. `mmap_size` lets reads come straight
# from a mapped region instead of being copied through that cache. Temporary
# B-trees — every GROUP BY that cannot use an index builds one — go to memory
# rather than to a file. And `synchronous = NORMAL` is the setting WAL was
# designed for: a crash can lose the last transaction, not the database, and
# nothing written here is worth an fsync per commit when it can be rebuilt.
#
# Measured, and worth knowing before anyone expects much: on a warm machine
# these change nothing. Reading 1.74M unit rows went 2.08s to 2.04s, which is
# noise. The file fits in the page cache the operating system already keeps,
# so there is no I/O left for a bigger cache or a mapped region to save. They
# are kept because they are right for the size of the file and cost nothing,
# not because they were seen to help — the case they address is a cold read,
# which is the one case a benchmark on this machine cannot produce.
TUNING = (
    # Declared and, until now, enforced almost nowhere. `sentence_units`
    # references `sentences(id)` with ON DELETE CASCADE, but only the
    # connection in `CorpusStore._connect` ever turned checking on — every
    # other reader and writer of this file could have left a row pointing at
    # a sentence that no longer exists, and the cascade would not have fired.
    #
    # Checked before switching it on: no orphan rows, and `foreign_key_check`
    # reports nothing. Enabling it costs a comparison per write against an
    # indexed parent key, which is not measurable beside the writes this
    # program makes in bulk.
    "PRAGMA foreign_keys = ON",
    "PRAGMA cache_size = -262144",
    "PRAGMA mmap_size = 536870912",
    "PRAGMA temp_store = MEMORY",
    "PRAGMA synchronous = NORMAL",
)


def open_state(path: Path) -> sqlite3.Connection:
    """A connection to the local state file, safe to use while others read."""
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    # Persistent once set, but re-issued because it costs nothing and a fresh
    # database file would otherwise keep the default until someone remembered.
    conn.execute("PRAGMA journal_mode = WAL")
    for pragma in TUNING:
        conn.execute(pragma)
    return conn
