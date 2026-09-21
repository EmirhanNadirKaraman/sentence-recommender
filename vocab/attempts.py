"""What you wrote with a word, and what came of it.

Every sentence written to practise a word — in the subtitle popup, on the
review page, in a Claude session over MCP — is an attempt, kept with the
word, the correction, the note and the verdict. The grade alone is what the
schedule needs; the attempt is what the *next* review needs: "last time you
wrote …, and the note was …" is the difference between being told a word
again and being told what you keep getting wrong with it. Claude reads the
history through `due_cards` for the same reason.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from state import open_state
from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempt (
    id        INTEGER PRIMARY KEY,
    kind      TEXT NOT NULL,
    key       TEXT NOT NULL,
    written   TEXT NOT NULL,
    german    TEXT,
    note      TEXT,
    english   TEXT,
    correct   INTEGER,
    place     TEXT NOT NULL,
    made_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_attempt_unit ON attempt (kind, key, made_at);
"""


class Attempts:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def add(self, unit: Unit, written: str, german: str | None, note: str | None,
            english: str | None, correct: bool | None, place: str,
            now: datetime | None = None) -> None:
        """One attempt. `correct` is None while nobody has graded it —
        the popup's check is advice, not a review."""
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT INTO attempt (kind, key, written, german, note, english,"
                " correct, place, made_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (unit.kind, unit.key, written, german, note, english,
                 None if correct is None else int(correct), place,
                 (now or datetime.now()).isoformat(timespec="seconds")))

    def grade_last(self, unit: Unit, correct: bool) -> None:
        """The verdict, once given, on the attempt it was given about."""
        with open_state(self._path) as conn:
            conn.execute(
                "UPDATE attempt SET correct = ? WHERE id = (SELECT id FROM attempt"
                " WHERE kind = ? AND key = ? ORDER BY made_at DESC, id DESC LIMIT 1)",
                (int(correct), unit.kind, unit.key))

    def of(self, unit: Unit, limit: int = 5) -> list[dict]:
        """The last attempts with a word, newest first."""
        with open_state(self._path) as conn:
            rows = conn.execute(
                "SELECT written, german, note, english, correct, place, made_at"
                " FROM attempt WHERE kind = ? AND key = ?"
                " ORDER BY made_at DESC, id DESC LIMIT ?",
                (unit.kind, unit.key, limit)).fetchall()
        return [{"written": w, "german": g or "", "note": n or "", "english": e or "",
                 "correct": None if c is None else bool(c), "place": p, "made_at": m}
                for w, g, n, e, c, p, m in rows]
