"""Words the reader has confirmed they know.

The quiz walks the assumed-known vocabulary asking "do you actually know
this", and until now it only wrote anything down when the answer was no — a
no comments the line out of the file, and a yes did nothing at all.

Which meant the quiz could not finish. It asks the most frequent words first,
a yes leaves the file exactly as it was, so the next run asks the same forty
and the run after that asks them again. Nine hundred and eighty-four words,
forty at a time, and no way past the first forty except to deny them.

So a yes is recorded too. Not in `known_units` — that is for words marked
while reading, and it feeds the roadmap; confirming a word that was already
assumed known changes nothing about what you know, only about what has been
checked. Two different facts, kept apart.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from state import open_state
from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS checked_units (
    kind    TEXT NOT NULL,
    key     TEXT NOT NULL,
    checked TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
"""


class CheckedStore:
    """Which assumed-known words have been confirmed, and when."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def confirm(self, unit: Unit) -> None:
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO checked_units (kind, key, checked)"
                " VALUES (?, ?, ?)",
                (unit.kind, unit.key, datetime.now().isoformat(timespec="seconds")))

    def forget(self, unit: Unit) -> None:
        """Ask about it again — for a word denied after having been confirmed."""
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM checked_units WHERE kind = ? AND key = ?",
                         (unit.kind, unit.key))

    def units(self) -> frozenset[Unit]:
        with open_state(self._path) as conn:
            return frozenset(Unit(kind, key) for kind, key in
                             conn.execute("SELECT kind, key FROM checked_units"))

    def __len__(self) -> int:
        with open_state(self._path) as conn:
            return conn.execute(
                "SELECT count(*) FROM checked_units").fetchone()[0]
