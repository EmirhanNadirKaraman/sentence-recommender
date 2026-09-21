"""Persistence for SRS cards — local SQLite, alongside the cached corpus."""
from __future__ import annotations

import sqlite3

from state import open_state
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
    lapses        INTEGER NOT NULL DEFAULT 0,
    UNIQUE (kind, key)
);
CREATE INDEX IF NOT EXISTS ix_cards_due ON cards(due_date);
"""


class CardStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)
            # A table from before lapses were counted.
            have = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
            if "lapses" not in have:
                conn.execute("ALTER TABLE cards ADD COLUMN lapses INTEGER NOT NULL DEFAULT 0")

    def add(self, card: Card) -> None:
        """Insert a card, leaving an existing one for the same unit alone —
        a claim made twice is one claim, with its history."""
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cards"
                " (kind, key, due_date, interval_days, ease_factor, repetitions,"
                "  last_review, lapses) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                self._to_row(card),
            )

    def add_many(self, cards: list[Card]) -> None:
        """Insert many cards in one transaction.

        `add` commits per call, which is a connection and an fsync each. A
        roadmap mints one card per step, so at eighteen thousand steps that
        alone outweighs the walk that produced them.
        """
        if not cards:
            return
        with open_state(self._path) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO cards"
                " (kind, key, due_date, interval_days, ease_factor, repetitions,"
                "  last_review, lapses) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [self._to_row(card) for card in cards],
            )

    def save(self, card: Card) -> None:
        with open_state(self._path) as conn:
            conn.execute(
                "UPDATE cards SET due_date = ?, interval_days = ?, ease_factor = ?,"
                " repetitions = ?, last_review = ?, lapses = ? WHERE kind = ? AND key = ?",
                (card.due_date.isoformat(), card.interval_days, card.ease_factor,
                 card.repetitions,
                 card.last_review.isoformat() if card.last_review else None,
                 card.lapses, card.unit.kind, card.unit.key),
            )

    def remove(self, unit: Unit) -> None:
        """Drop a unit's card: the claim graduated, or was withdrawn."""
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM cards WHERE kind = ? AND key = ?",
                         (unit.kind, unit.key))

    def get(self, unit: Unit) -> Card | None:
        """One unit's card, or None when it has none — a word marked known
        has had its card removed, and a word the roadmap never reached never
        had one."""
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT card_id, kind, key, due_date, interval_days, ease_factor,"
                " repetitions, last_review, lapses FROM cards WHERE kind = ? AND key = ?",
                (unit.kind, unit.key),
            ).fetchone()
        return self._from_row(row) if row else None

    def due(self, now: datetime, limit: int = 20) -> list[Card]:
        with open_state(self._path) as conn:
            rows = conn.execute(
                "SELECT card_id, kind, key, due_date, interval_days, ease_factor,"
                " repetitions, last_review, lapses FROM cards WHERE due_date <= ?"
                " ORDER BY due_date LIMIT ?",
                (now.isoformat(), limit),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def counts(self, now: datetime) -> tuple[int, int]:
        """(total cards, cards due now)."""
        with open_state(self._path) as conn:
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
            card.lapses,
        )

    @staticmethod
    def _from_row(row: tuple) -> Card:
        card_id, kind, key, due, interval, ease, reps, last, lapses = row
        return Card(
            unit=Unit(kind, key),
            due_date=datetime.fromisoformat(due),
            interval_days=interval,
            ease_factor=ease,
            repetitions=reps,
            last_review=datetime.fromisoformat(last) if last else None,
            lapses=lapses,
            card_id=card_id,
        )
