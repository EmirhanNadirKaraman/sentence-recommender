"""Persistence for generated roadmaps.

Filed by source, because a roadmap over the video subtitles and one over
everything are different curricula rather than two views of the same one.
Keeping both lets the viewer switch between them without a rebuild.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from corpus.sentence import Sentence
from roadmap.step import RoadmapStep
from vocab.entry import Unit

# The label a roadmap built from every cached corpus is filed under.
ALL = "all"

SCHEMA = """
CREATE TABLE IF NOT EXISTS roadmap (
    source       TEXT NOT NULL DEFAULT 'all',
    position     INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    key          TEXT NOT NULL,
    sentence     TEXT NOT NULL,
    translation  TEXT,
    origin       TEXT NOT NULL,
    surface      TEXT,
    gain         INTEGER NOT NULL,
    score        REAL NOT NULL,
    now_readable INTEGER NOT NULL,
    PRIMARY KEY (source, position)
);
"""

COLUMNS = ("position, kind, key, sentence, translation, origin, surface,"
           " gain, score, now_readable")


class RoadmapStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            self._ensure_schema(conn)

    @staticmethod
    def _ensure_schema(conn) -> None:
        """Create the table, dropping a pre-source one if it is still there.

        The old table keyed on position alone, so it cannot hold two roadmaps
        at once. Rebuilding one takes seconds; migrating the rows would be
        more code than it saves.
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(roadmap)")}
        if columns and "source" not in columns:
            conn.execute("DROP TABLE roadmap")
        conn.executescript(SCHEMA)

    def sources(self) -> dict[str, int]:
        """Which roadmaps exist, and how long each is."""
        with sqlite3.connect(self._path) as conn:
            return dict(conn.execute(
                "SELECT source, count(*) FROM roadmap GROUP BY source"))

    def save(self, steps: list[RoadmapStep], source: str = ALL) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute("DELETE FROM roadmap WHERE source = ?", (source,))
            conn.executemany(
                f"INSERT INTO roadmap (source, {COLUMNS})"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(source, s.position, s.unit.kind, s.unit.key, s.sentence.text,
                  s.sentence.translation, s.sentence.origin,
                  s.sentence.surface_of(s.unit), s.gain, s.score,
                  s.now_readable) for s in steps],
            )

    def load(self, source: str = ALL, limit: int | None = None) -> list[RoadmapStep]:
        query = (f"SELECT {COLUMNS} FROM roadmap WHERE source = ? ORDER BY position")
        if limit:
            query += f" LIMIT {int(limit)}"
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(query, (source,)).fetchall()
        return [
            RoadmapStep(
                position=position,
                unit=Unit(kind, key),
                # The surface travels with the step so a reader can be shown
                # which word in the sentence is the new one — "hat" for "haben".
                sentence=Sentence(
                    text=text, origin=origin, translation=translation,
                    surfaces=((Unit(kind, key), surface),) if surface else (),
                ),
                gain=gain,
                score=score,
                now_readable=now_readable,
            )
            for position, kind, key, text, translation, origin, surface, gain,
                score, now_readable in rows
        ]

    def count(self, source: str = ALL) -> int:
        with sqlite3.connect(self._path) as conn:
            return conn.execute(
                "SELECT count(*) FROM roadmap WHERE source = ?", (source,)
            ).fetchone()[0]
