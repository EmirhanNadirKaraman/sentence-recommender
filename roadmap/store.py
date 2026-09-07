"""Persistence for a generated roadmap."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from corpus.sentence import Sentence
from roadmap.step import RoadmapStep
from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS roadmap (
    position     INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,
    key          TEXT NOT NULL,
    sentence     TEXT NOT NULL,
    translation  TEXT,
    origin       TEXT NOT NULL,
    gain         INTEGER NOT NULL,
    score        REAL NOT NULL,
    now_readable INTEGER NOT NULL
);
"""


class RoadmapStore:
    """The generated sequence, kept so it can be reread without rebuilding."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.executescript(SCHEMA)

    def save(self, steps: list[RoadmapStep]) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute("DELETE FROM roadmap")
            conn.executemany(
                "INSERT INTO roadmap (position, kind, key, sentence, translation,"
                " origin, gain, score, now_readable) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(s.position, s.unit.kind, s.unit.key, s.sentence.text,
                  s.sentence.translation, s.sentence.origin, s.gain, s.score,
                  s.now_readable) for s in steps],
            )

    def load(self, limit: int | None = None) -> list[RoadmapStep]:
        query = "SELECT * FROM roadmap ORDER BY position"
        if limit:
            query += f" LIMIT {int(limit)}"
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(query).fetchall()
        return [
            RoadmapStep(
                position=position,
                unit=Unit(kind, key),
                sentence=Sentence(text=text, origin=origin, translation=translation),
                gain=gain,
                score=score,
                now_readable=now_readable,
            )
            for position, kind, key, text, translation, origin, gain, score,
                now_readable in rows
        ]

    def count(self) -> int:
        with sqlite3.connect(self._path) as conn:
            return conn.execute("SELECT count(*) FROM roadmap").fetchone()[0]
