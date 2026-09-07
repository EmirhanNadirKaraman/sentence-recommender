"""Persistence for SRS cards — local SQLite, alongside the cached corpus."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from srs.card import Card
from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    card_id       INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,
    key           TEXT NOT NULL,
    due_date      TEXT NOT NULL,
    interval_days REAL NOT NULL,
    ease_factor   REAL NOT NULL,
    repetitions   INTEGER NOT NULL,
    last_review   TEXT,
    UNIQUE (kind, key)
);
CREATE INDEX IF NOT EXISTS ix_cards_due ON cards(due_date);
"""


class CardStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.executescript(SCHEMA)

    def add(self, card: Card) -> None:
        """Insert a card, leaving an existing one for the same unit alone —
        rebuilding a roadmap must not reset review history."""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cards"
                " (kind, key, due_date, interval_days, ease_factor, repetitions,"
                "  last_review) VALUES (?, ?, ?, ?, ?, ?, ?)",
                self._to_row(card),
            )

    def save(self, card: Card) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "UPDATE cards SET due_date = ?, interval_days = ?, ease_factor = ?,"
                " repetitions = ?, last_review = ? WHERE kind = ? AND key = ?",
                (card.due_date.isoformat(), card.interval_days, card.ease_factor,
                 card.repetitions,
                 card.last_review.isoformat() if card.last_review else None,
                 card.unit.kind, card.unit.key),
            )

    def due(self, now: datetime, limit: int = 20) -> list[Card]:
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT card_id, kind, key, due_date, interval_days, ease_factor,"
                " repetitions, last_review FROM cards WHERE due_date <= ?"
                " ORDER BY due_date LIMIT ?",
                (now.isoformat(), limit),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def counts(self, now: datetime) -> tuple[int, int]:
        """(total cards, cards due now)."""
        with sqlite3.connect(self._path) as conn:
            total = conn.execute("SELECT count(*) FROM cards").fetchone()[0]
            due = conn.execute(
                "SELECT count(*) FROM cards WHERE due_date <= ?", (now.isoformat(),)
            ).fetchone()[0]
        return total, due

    @staticmethod
    def _to_row(card: Card) -> tuple:
        return (
            card.unit.kind, card.unit.key, card.due_date.isoformat(),
            card.interval_days, card.ease_factor, card.repetitions,
            card.last_review.isoformat() if card.last_review else None,
        )

    @staticmethod
    def _from_row(row: tuple) -> Card:
        card_id, kind, key, due, interval, ease, reps, last = row
        return Card(
            unit=Unit(kind, key),
            due_date=datetime.fromisoformat(due),
            interval_days=interval,
            ease_factor=ease,
            repetitions=reps,
            last_review=datetime.fromisoformat(last) if last else None,
            card_id=card_id,
        )
