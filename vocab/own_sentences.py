"""The sentences you wrote to say — and when to ask you for them again.

Everything else here is somebody else's German. These are yours: a thing you
wanted to say, written in English or in German, put into German by the local
model, read over and saved. Two things follow from one being yours. It is
worth more than a stranger's sentence as an example of its words, so it goes
into the corpus too (`Application.adopt`), under the `generated` build with
`origin` "own", and stands first on the cards of the words in it. And it is
worth being able to *produce*, not only read, so each one is scheduled:
shown to you as English, answered in German, graded by you, and spaced by
the same SM-2 the word cards use (`srs.scheduler`).

Kept apart from the word cards on purpose: a word card asks about a unit and
is built from example sentences; this asks for one sentence and is built
from nothing but itself.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from srs.card import Card
from srs.scheduler import SM2Scheduler
from state import open_state
from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS own_sentence (
    text          TEXT PRIMARY KEY,
    english       TEXT NOT NULL,
    made_at       TEXT NOT NULL,
    due_date      TEXT NOT NULL,
    interval_days REAL NOT NULL,
    ease_factor   REAL NOT NULL,
    repetitions   INTEGER NOT NULL,
    last_review   TEXT
);
"""

KIND = "sentence"


class OwnSentences:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)
        self._scheduler = SM2Scheduler()

    def add(self, text: str, english: str, now: datetime | None = None) -> None:
        """Save one, due at once: a sentence you just wrote is the first
        thing to be asked for."""
        now = now or datetime.now()
        card = self._scheduler.new_card(Unit(KIND, text), now)
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT INTO own_sentence (text, english, made_at, due_date,"
                " interval_days, ease_factor, repetitions, last_review)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, NULL)"
                " ON CONFLICT(text) DO UPDATE SET english = excluded.english",
                (text, english, now.isoformat(timespec="seconds"),
                 card.due_date.isoformat(), card.interval_days, card.ease_factor,
                 card.repetitions))

    def remove(self, text: str) -> None:
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM own_sentence WHERE text = ?", (text,))

    def all(self) -> list[dict]:
        """Every sentence, newest first, with its schedule."""
        with open_state(self._path) as conn:
            rows = conn.execute(
                "SELECT text, english, made_at, due_date, interval_days,"
                " repetitions, last_review FROM own_sentence ORDER BY made_at DESC"
            ).fetchall()
        return [{"text": t, "english": e, "made_at": m, "due": d,
                 "interval": i, "repetitions": r, "last": last}
                for t, e, m, d, i, r, last in rows]

    def texts(self) -> frozenset[str]:
        with open_state(self._path) as conn:
            return frozenset(t for (t,) in conn.execute("SELECT text FROM own_sentence"))

    def due(self, now: datetime | None = None) -> list[dict]:
        """The ones to ask for now, the longest overdue first."""
        now = (now or datetime.now()).isoformat()
        with open_state(self._path) as conn:
            rows = conn.execute(
                "SELECT text, english, due_date FROM own_sentence"
                " WHERE due_date <= ? ORDER BY due_date", (now,)).fetchall()
        return [{"text": t, "english": e, "due": d} for t, e, d in rows]

    def grade(self, text: str, correct: bool, now: datetime | None = None) -> None:
        """You said it, or you did not: the next asking moves accordingly."""
        now = now or datetime.now()
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT due_date, interval_days, ease_factor, repetitions, last_review"
                " FROM own_sentence WHERE text = ?", (text,)).fetchone()
            if row is None:
                return
            due, interval, ease, reps, last = row
            card = Card(Unit(KIND, text), datetime.fromisoformat(due), interval, ease, reps,
                        datetime.fromisoformat(last) if last else None)
            after = self._scheduler.review(card, correct, now)
            conn.execute(
                "UPDATE own_sentence SET due_date = ?, interval_days = ?, ease_factor = ?,"
                " repetitions = ?, last_review = ? WHERE text = ?",
                (after.due_date.isoformat(), after.interval_days, after.ease_factor,
                 after.repetitions, now.isoformat(timespec="seconds"), text))
