"""Local cache of the assembled corpus.

Analysing the corpus costs real time — a couple of minutes for the subtitles
— and none of it depends on anything the user does between runs.  So the
result is cached here and rebuilt only when asked.

This is the only file in the project that writes anything, and it writes to a
local SQLite file.  The Postgres database is never touched.

Rows are keyed by `build`, a label naming both the source and how it was
assembled (`subtitle`, `subtitle:llm`).  Without that key one way of
assembling the subtitles would overwrite another.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from fingerprint import analyser_fingerprint
from state import open_state
from pathlib import Path

from alignment.timing import Timing
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
    source_ids  TEXT NOT NULL DEFAULT '',
    video_id    TEXT,
    start_time  REAL,
    end_time    REAL,
    teachable   INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_sentences_build ON sentences(build);
CREATE TABLE IF NOT EXISTS sentence_units (
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    surface     TEXT
);
CREATE INDEX IF NOT EXISTS ix_units_sentence ON sentence_units(sentence_id);
CREATE TABLE IF NOT EXISTS build_meta (
    build       TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    made_at     TEXT NOT NULL
);
"""


class CorpusStore:
    """Reads and writes cached corpus builds."""

    def __init__(self, path: Path, ignored: frozenset[str] = frozenset()) -> None:
        self._path = path
        # Builds that exist in the file but are not studied from. Hidden here
        # rather than deleted, so the rows survive and one setting brings them
        # back. `load` still returns them if asked by name — only the "every
        # build" default and the source picker skip them.
        self._ignored = ignored
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._add_missing_columns(conn)

    @staticmethod
    def _add_missing_columns(conn) -> None:
        """Bring an older cache file up to the current shape.

        The tables are created with IF NOT EXISTS, so a database written before
        a column existed keeps its old shape and every read fails. Adding what
        is missing is cheaper than asking for a rebuild that costs minutes.
        """
        existing = {row[1] for row in conn.execute("PRAGMA table_info(sentences)")}
        for column, kind in (("video_id", "TEXT"), ("start_time", "REAL"),
                             ("end_time", "REAL"),
                             ("teachable", "INTEGER NOT NULL DEFAULT 1")):
            if column not in existing:
                conn.execute(f"ALTER TABLE sentences ADD COLUMN {column} {kind}")

    def _connect(self) -> sqlite3.Connection:
        conn = open_state(self._path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def builds(self, teachable_only: bool = False) -> dict[str, int]:
        """Build name -> how many sentences it holds.

        `teachable_only` counts what the roadmap can actually use, leaving out
        the rows a subtitle build keeps purely so the overlay has no gaps.
        """
        where = " WHERE teachable = 1" if teachable_only else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT build, count(*) FROM sentences{where} GROUP BY build")
            return {b: n for b, n in rows if b not in self._ignored}

    def video_ids(self, build: str) -> set[str]:
        """Which videos a build already holds, so the rest can be skipped."""
        with self._connect() as conn:
            return {row[0] for row in conn.execute(
                "SELECT DISTINCT video_id FROM sentences"
                " WHERE build = ? AND video_id IS NOT NULL", (build,))}

    def append(self, sentences: list[Sentence], build: str) -> None:
        """Add to a build without disturbing what is already in it."""
        self._write(sentences, build)
        self._stamp(build)

    def save(self, sentences: list[Sentence], build: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sentence_units WHERE sentence_id IN"
                " (SELECT id FROM sentences WHERE build = ?)", (build,))
            conn.execute("DELETE FROM sentences WHERE build = ?", (build,))
        self._write(sentences, build)
        self._stamp(build)

    def stale(self) -> dict[str, str]:
        """Builds whose fingerprint no longer matches the rules in force.

        Name -> the fingerprint it was made with. A build with no record at
        all counts as stale: it predates this bookkeeping, so nothing can
        vouch for it.
        """
        now = analyser_fingerprint()
        with self._connect() as conn:
            stored = dict(conn.execute("SELECT build, fingerprint FROM build_meta"))
        return {b: stored.get(b, "unrecorded") for b in self.builds()
                if stored.get(b) != now}

    def _stamp(self, build: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO build_meta (build, fingerprint, made_at)"
                " VALUES (?, ?, ?) ON CONFLICT(build) DO UPDATE SET"
                " fingerprint = excluded.fingerprint, made_at = excluded.made_at",
                (build, analyser_fingerprint(), datetime.now().isoformat(timespec="seconds")),
            )

    def _write(self, sentences: list[Sentence], build: str) -> None:
        with self._connect() as conn:
            for sentence in sentences:
                cursor = conn.execute(
                    "INSERT INTO sentences"
                    " (build, origin, text, translation, raw_text, source_ids,"
                    "  video_id, start_time, end_time, teachable)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (build, sentence.origin, sentence.text, sentence.translation,
                     sentence.raw_text,
                     ",".join(str(i) for i in sentence.source_ids),
                     *self._timing_row(sentence), int(sentence.teachable)),
                )
                conn.executemany(
                    "INSERT INTO sentence_units (sentence_id, kind, key, surface)"
                    " VALUES (?, ?, ?, ?)",
                    [(cursor.lastrowid, u.kind, u.key, sentence.surface_of(u))
                     for u in sentence.units],
                )

    @staticmethod
    def _timing_row(sentence: Sentence) -> tuple:
        timing = sentence.timing
        return (timing.video_id, timing.start, timing.end) if timing else (None, None, None)

    def load(self, *builds: str, teachable_only: bool = True) -> list[Sentence]:
        """Cached sentences.  By default only the ones worth studying from —
        pass `teachable_only=False` for the full transcript, which is what an
        overlay needs."""
        if not builds:
            return []          # `WHERE build IN ()` is not valid SQL
        placeholders = ",".join("?" * len(builds))
        teachable = " AND teachable = 1" if teachable_only else ""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, origin, text, translation, raw_text, source_ids,"
                " video_id, start_time, end_time, teachable"
                f" FROM sentences WHERE build IN ({placeholders}){teachable}", builds,
            ).fetchall()
            units: dict[int, set[Unit]] = {}
            surfaces: dict[int, list[tuple[Unit, str]]] = {}
            # Two million unit rows across forty thousand distinct units, so
            # nearly every one is a repeat. Interning them turns most of those
            # rows into a dict lookup instead of an object, which is most of
            # the cost of loading a large corpus.
            seen: dict[tuple[str, str], Unit] = {}
            for sid, kind, key, surface in conn.execute(
                "SELECT su.sentence_id, su.kind, su.key, su.surface FROM sentence_units su"
                " JOIN sentences s ON s.id = su.sentence_id"
                f" WHERE s.build IN ({placeholders})", builds,
            ):
                unit = seen.get((kind, key))
                if unit is None:
                    unit = seen[(kind, key)] = Unit(kind, key)
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
                timing=(
                    Timing(video_id, start_time, end_time)
                    if video_id is not None and start_time is not None else None
                ),
                teachable=bool(teachable_flag),
            )
            for sid, origin, text, translation, raw_text, source_ids,
                video_id, start_time, end_time, teachable_flag in rows
        ]
