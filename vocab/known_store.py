"""Words and patterns marked as known while reading.

The vocabulary files are the starting point; this is what accumulates on top
of them. Kept apart from `known_words.txt` deliberately — that file is
hand-written and belongs to the reader, and a program that rewrites it would
make it untrustworthy.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS known_units (
    kind     TEXT NOT NULL,
    key      TEXT NOT NULL,
    marked   TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
"""


class KnownStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.executescript(SCHEMA)

    def add(self, unit: Unit) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO known_units (kind, key, marked)"
                " VALUES (?, ?, ?)",
                (unit.kind, unit.key, datetime.now().isoformat()),
            )

    def remove(self, unit: Unit) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute("DELETE FROM known_units WHERE kind = ? AND key = ?",
                         (unit.kind, unit.key))

    def units(self) -> set[Unit]:
        with sqlite3.connect(self._path) as conn:
            return {Unit(kind, key) for kind, key in
                    conn.execute("SELECT kind, key FROM known_units")}

    def __len__(self) -> int:
        with sqlite3.connect(self._path) as conn:
            return conn.execute("SELECT count(*) FROM known_units").fetchone()[0]
