"""Words and patterns marked as known while reading.

The vocabulary files are the starting point; this is what accumulates on top
of them. Kept apart from `known_words.txt` deliberately — that file is
hand-written and belongs to the reader, and a program that rewrites it would
make it untrustworthy.
"""
from __future__ import annotations

import sqlite3

from state import open_state
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

-- A counter, bumped by the database itself whenever this table changes.
-- Anything derived from what you know — every video's comprehension score —
-- is stamped with it and recomputed when the stamps disagree.
--
-- A trigger rather than a call in `add`, because a caller can forget and a
-- trigger cannot: the row cannot change without the version moving, whoever
-- writes it and by whatever route.
CREATE TABLE IF NOT EXISTS known_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
INSERT OR IGNORE INTO known_version (id, version) VALUES (1, 0);

CREATE TRIGGER IF NOT EXISTS known_units_added AFTER INSERT ON known_units
BEGIN UPDATE known_version SET version = version + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS known_units_removed AFTER DELETE ON known_units
BEGIN UPDATE known_version SET version = version + 1 WHERE id = 1; END;
"""


class KnownStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def version(self) -> int:
        """How many times what you know has changed.

        Cheap enough to ask on every request, which is the point: it decides
        whether a stored score still describes you.
        """
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT version FROM known_version WHERE id = 1").fetchone()
        return row[0] if row else 0

    def add(self, unit: Unit) -> None:
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO known_units (kind, key, marked)"
                " VALUES (?, ?, ?)",
                (unit.kind, unit.key, datetime.now().isoformat()),
            )

    def remove(self, unit: Unit) -> None:
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM known_units WHERE kind = ? AND key = ?",
                         (unit.kind, unit.key))

    def units(self) -> set[Unit]:
        with open_state(self._path) as conn:
            return {Unit(kind, key) for kind, key in
                    conn.execute("SELECT kind, key FROM known_units")}

    def __len__(self) -> int:
        with open_state(self._path) as conn:
            return conn.execute("SELECT count(*) FROM known_units").fetchone()[0]
