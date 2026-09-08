"""Local cache of the assembled corpus.

Analysing the corpus costs real time — a minute for the subtitles, far longer
for Tatoeba's 276k pairs — and none of it depends on anything the user does
between runs.  So the result is cached here and rebuilt only when asked.

This is the only file in the project that writes anything, and it writes to a
local SQLite file.  The Postgres database is never touched.

Rows are keyed by `build`, a label naming both the source and how it was
assembled (`tatoeba`, `subtitle:merge`, `subtitle:llm`).  Without that key a
Tatoeba run would overwrite a subtitle run.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from corpus.sentence import Sentence
from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentences (
    id          INTEGER PRIMARY KEY,
    build       TEXT NOT NULL,
    origin      TEXT NOT NULL,
    text        TEXT NOT NULL,
    translation TEXT,
    raw_text    TEXT,
    source_ids  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_sentences_build ON sentences(build);
CREATE TABLE IF NOT EXISTS sentence_units (
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    surface     TEXT
);
CREATE INDEX IF NOT EXISTS ix_units_sentence ON sentence_units(sentence_id);
"""


class CorpusStore:
    """Reads and writes cached corpus builds."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def builds(self) -> dict[str, int]:
        with self._connect() as conn:
            return dict(conn.execute(
                "SELECT build, count(*) FROM sentences GROUP BY build"
            ))

    def save(self, sentences: list[Sentence], build: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sentence_units WHERE sentence_id IN"
                " (SELECT id FROM sentences WHERE build = ?)", (build,))
            conn.execute("DELETE FROM sentences WHERE build = ?", (build,))
            for sentence in sentences:
                cursor = conn.execute(
                    "INSERT INTO sentences"
                    " (build, origin, text, translation, raw_text, source_ids)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (build, sentence.origin, sentence.text, sentence.translation,
                     sentence.raw_text,
                     ",".join(str(i) for i in sentence.source_ids)),
                )
                conn.executemany(
                    "INSERT INTO sentence_units (sentence_id, kind, key, surface)"
                    " VALUES (?, ?, ?, ?)",
                    [(cursor.lastrowid, u.kind, u.key, sentence.surface_of(u))
                     for u in sentence.units],
                )

    def load(self, *builds: str) -> list[Sentence]:
        if not builds:
            return []          # `WHERE build IN ()` is not valid SQL
        placeholders = ",".join("?" * len(builds))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, origin, text, translation, raw_text, source_ids"
                f" FROM sentences WHERE build IN ({placeholders})", builds,
            ).fetchall()
            units: dict[int, set[Unit]] = {}
            surfaces: dict[int, list[tuple[Unit, str]]] = {}
            for sid, kind, key, surface in conn.execute(
                "SELECT su.sentence_id, su.kind, su.key, su.surface FROM sentence_units su"
                " JOIN sentences s ON s.id = su.sentence_id"
                f" WHERE s.build IN ({placeholders})", builds,
            ):
                unit = Unit(kind, key)
                units.setdefault(sid, set()).add(unit)
                if surface:
                    surfaces.setdefault(sid, []).append((unit, surface))
        return [
            Sentence(
                text=text,
                origin=origin,
                translation=translation,
                raw_text=raw_text,
                source_ids=tuple(int(i) for i in source_ids.split(",") if i),
                units=frozenset(units.get(sid, ())),
                surfaces=tuple(surfaces.get(sid, ())),
            )
            for sid, origin, text, translation, raw_text, source_ids in rows
        ]
