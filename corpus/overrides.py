"""Reader corrections to what the analyser decided.

The analyser is right most of the time and wrong in ways no threshold catches:
a sentence that is nonsense out of context, a word it split badly, a pattern
it invented. Two corrections are possible here — hide the sentence, or say
what its units actually are — and both outrank whatever the analyser thought.

Keyed by sentence text rather than row id. The corpus is rebuilt from scratch
whenever the analyser changes, and ids change with it; a correction that
vanished on the next rebuild would be worse than no correction at all.
"""
from __future__ import annotations

import sqlite3

from state import open_state
from datetime import datetime
from pathlib import Path

from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS hidden_sentences (
    text     TEXT PRIMARY KEY,
    hidden   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sentence_units_override (
    text     TEXT NOT NULL,
    kind     TEXT NOT NULL,
    key      TEXT NOT NULL,
    surface  TEXT,
    PRIMARY KEY (text, kind, key)
);
CREATE TABLE IF NOT EXISTS corrected_sentences (
    text      TEXT PRIMARY KEY,
    corrected TEXT NOT NULL
);
"""


class SentenceOverrides:
    """What the reader has said about particular sentences."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    # --- hiding ----------------------------------------------------------

    def hide(self, text: str) -> None:
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO hidden_sentences (text, hidden)"
                " VALUES (?, ?)", (text, datetime.now().isoformat()))

    def show(self, text: str) -> None:
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM hidden_sentences WHERE text = ?", (text,))

    def hidden(self) -> set[str]:
        with open_state(self._path) as conn:
            return {row[0] for row in
                    conn.execute("SELECT text FROM hidden_sentences")}

    # --- correcting the units --------------------------------------------

    def set_units(self, text: str, units: dict[Unit, str]) -> None:
        """Replace what a sentence is taken to contain.

        An empty set is meaningful and kept: it says this sentence teaches
        nothing, which is different from having no opinion about it.
        """
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM sentence_units_override WHERE text = ?",
                         (text,))
            conn.executemany(
                "INSERT INTO sentence_units_override (text, kind, key, surface)"
                " VALUES (?, ?, ?, ?)",
                [(text, u.kind, u.key, surface) for u, surface in units.items()],
            )
            conn.execute(
                "INSERT OR REPLACE INTO corrected_sentences (text, corrected)"
                " VALUES (?, ?)", (text, datetime.now().isoformat()))

    def clear_units(self, text: str) -> None:
        """Forget the correction and go back to what the analyser said."""
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM sentence_units_override WHERE text = ?",
                         (text,))
            conn.execute("DELETE FROM corrected_sentences WHERE text = ?", (text,))

    def corrected(self) -> dict[str, dict[Unit, str]]:
        """Every correction, as sentence text -> units and their surfaces."""
        with open_state(self._path) as conn:
            corrected = {row[0]: {} for row in
                         conn.execute("SELECT text FROM corrected_sentences")}
            for text, kind, key, surface in conn.execute(
                "SELECT text, kind, key, surface FROM sentence_units_override"
            ):
                corrected.setdefault(text, {})[Unit(kind, key)] = surface or ""
        return corrected

    def counts(self) -> tuple[int, int]:
        with open_state(self._path) as conn:
            hidden = conn.execute(
                "SELECT count(*) FROM hidden_sentences").fetchone()[0]
            fixed = conn.execute(
                "SELECT count(*) FROM corrected_sentences").fetchone()[0]
        return hidden, fixed
