"""Persistence for generated roadmaps.

Filed by source, because a roadmap over the video subtitles and one over
everything are different curricula rather than two views of the same one.
Keeping both lets the viewer switch between them without a rebuild.

A step carries the deck of sentences that teach it, written down during the
walk.  That is the whole reason the reading page can open without a corpus:
everything it shows — the sentences, what else is new in each, the video each
came from, the two counts in the headline — was decided when the roadmap was
built and is read back from here in a single query.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from state import open_state
from pathlib import Path

from alignment.timing import Timing
from corpus.quality import VERSION as QUALITY_VERSION
from corpus.sentence import Sentence
from fingerprint import analyser_fingerprint
from roadmap.step import RoadmapStep
from vocab.entry import Unit

# The label a roadmap built from every cached corpus is filed under.
ALL = "all"

# Bumped when the shape of what is stored changes — a deck ranked a different
# way, a column that means something new. The analyser fingerprint catches a
# rebuilt corpus but not a rewritten walk, and a stamp that only watches its
# inputs will happily vouch for output the current code would never produce.
ROADMAP_VERSION = 2


def current_stamp() -> str:
    """What a roadmap built right now would be stamped with.

    The analyser, because a rebuilt corpus holds different sentences and the
    stored decks name theirs by text alone; the quality version, because it
    decides which sentences reach a deck and in what order; and this module's
    own version.
    """
    return f"{analyser_fingerprint()}|{ROADMAP_VERSION}|{QUALITY_VERSION}"

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
    readable     INTEGER NOT NULL DEFAULT 0,
    occurrences  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, position)
);

CREATE TABLE IF NOT EXISTS roadmap_example (
    source      TEXT NOT NULL,
    position    INTEGER NOT NULL,
    n           INTEGER NOT NULL,
    text        TEXT NOT NULL,
    translation TEXT,
    origin      TEXT NOT NULL,
    surface     TEXT,
    units       TEXT NOT NULL,
    video_id    TEXT,
    start_time  REAL,
    end_time    REAL,
    PRIMARY KEY (source, position, n)
);

CREATE TABLE IF NOT EXISTS roadmap_meta (
    source  TEXT PRIMARY KEY,
    stamp   TEXT NOT NULL,
    made_at TEXT NOT NULL,
    total   INTEGER NOT NULL DEFAULT 0
);
"""

COLUMNS = ("position, kind, key, sentence, translation, origin, surface,"
           " gain, score, now_readable, readable, occurrences")

EXAMPLE_COLUMNS = ("position, n, text, translation, origin, surface, units,"
                   " video_id, start_time, end_time")


class RoadmapStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            self._ensure_schema(conn)

    @classmethod
    def _ensure_schema(cls, conn) -> None:
        """Create the tables, dropping a pre-source roadmap if it is still there.

        The old table keyed on position alone, so it cannot hold two roadmaps
        at once. Rebuilding one takes seconds; migrating the rows would be
        more code than it saves.
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(roadmap)")}
        if columns and "source" not in columns:
            conn.execute("DROP TABLE roadmap")
        conn.executescript(SCHEMA)
        cls._add_missing_columns(conn)

    @staticmethod
    def _add_missing_columns(conn) -> None:
        """Bring a roadmap written by an older version up to the current shape.

        `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
        exists, so a column added later has to be added by hand or the first
        write against an older database fails.  The defaults are what an old
        row honestly says: nothing was recorded, and the page falls back to
        counting for itself.
        """
        for table, added in (("roadmap", ("readable", "occurrences")),
                             ("roadmap_meta", ("total",))):
            columns = {row[1] for row in
                       conn.execute(f"PRAGMA table_info({table})")}
            for name in added:
                if name not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name}"
                                 " INTEGER NOT NULL DEFAULT 0")

    def sources(self) -> dict[str, int]:
        """Which roadmaps exist, and how long each is."""
        with open_state(self._path) as conn:
            return dict(conn.execute(
                "SELECT source, count(*) FROM roadmap GROUP BY source"))

    def stamp(self, source: str = ALL) -> str | None:
        """What this roadmap was built from, or None if nothing was recorded.

        The stored decks name sentences by their text alone, so a roadmap
        outlives the corpus that produced it without any sign of trouble: the
        page keeps serving sentences that may no longer be in the corpus at
        all.  The stamp is how a reader of the store can tell.
        """
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT stamp FROM roadmap_meta WHERE source = ?",
                (source,)).fetchone()
        return row[0] if row else None

    def total(self, source: str = ALL) -> int:
        """How many sentences this roadmap was walked over.

        The denominator the reading page states its progress against. Stored
        rather than counted, because counting it means holding the corpus —
        and because it is not the size of the corpus but the size of the slice
        the walk was given: `--quality` builds over 41,394 of 115,461, and a
        page that showed progress against the larger number would be quietly
        answering a question nobody asked.
        """
        with open_state(self._path) as conn:
            row = conn.execute(
                "SELECT total FROM roadmap_meta WHERE source = ?",
                (source,)).fetchone()
        return row[0] if row else 0

    def append(self, steps: list[RoadmapStep], source: str = ALL,
               stamp: str = "", total: int = 0) -> None:
        """Add steps to a roadmap, leaving the ones already there alone.

        What a reader has already been shown keeps its position: a new video
        should lengthen the plan, not renumber it underneath them.  The stamp
        moves to the corpus that produced the extension, which is also the one
        the earlier steps were checked against when the walk resumed.
        """
        self._insert(steps, source, stamp, total)

    def save(self, steps: list[RoadmapStep], source: str = ALL,
             stamp: str = "", total: int = 0) -> None:
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM roadmap WHERE source = ?", (source,))
            conn.execute("DELETE FROM roadmap_example WHERE source = ?",
                         (source,))
        self._insert(steps, source, stamp, total)

    def _insert(self, steps: list[RoadmapStep], source: str,
                stamp: str = "", total: int = 0) -> None:
        with open_state(self._path) as conn:
            conn.executemany(
                f"INSERT INTO roadmap (source, {COLUMNS})"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(source, s.position, s.unit.kind, s.unit.key, s.sentence.text,
                  s.sentence.translation, s.sentence.origin,
                  s.sentence.surface_of(s.unit), s.gain, s.score,
                  s.now_readable, s.readable, s.occurrences) for s in steps],
            )
            conn.executemany(
                f"INSERT OR REPLACE INTO roadmap_example (source,"
                f" {EXAMPLE_COLUMNS})"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [self._example_row(source, step, n, example)
                 for step in steps
                 for n, example in enumerate(step.examples)],
            )
            if stamp:
                conn.execute(
                    "INSERT OR REPLACE INTO roadmap_meta"
                    " (source, stamp, made_at, total) VALUES (?, ?, ?, ?)",
                    (source, stamp,
                     datetime.now().isoformat(timespec="seconds"), total))

    @staticmethod
    def _example_row(source: str, step: RoadmapStep, n: int,
                     example: Sentence) -> tuple:
        # The units travel with the sentence because the page says what *else*
        # in it is new, and that has to be answered against whatever the
        # reader knows right now — so it cannot be decided here.
        units = json.dumps(sorted([u.kind, u.key] for u in example.units))
        timing = example.timing
        return (source, step.position, n, example.text, example.translation,
                example.origin, example.surface_of(step.unit), units,
                timing.video_id if timing else None,
                timing.start if timing else None,
                timing.end if timing else None)

    def load(self, source: str = ALL, limit: int | None = None) -> list[RoadmapStep]:
        """The steps, without their decks.

        The decks are left behind on purpose: the roadmap runs to thousands of
        steps with a couple of dozen sentences each, and every page that wants
        the list wants one line per step.  `deck` fetches the one that is
        actually being read.
        """
        query = (f"SELECT {COLUMNS} FROM roadmap WHERE source = ? ORDER BY position")
        if limit:
            query += f" LIMIT {int(limit)}"
        with open_state(self._path) as conn:
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
                readable=readable,
                occurrences=occurrences,
            )
            for position, kind, key, text, translation, origin, surface, gain,
                score, now_readable, readable, occurrences in rows
        ]

    def deck(self, source: str, step: RoadmapStep) -> list[Sentence]:
        """The stored deck for one step, in the order the walk ranked it.

        Takes the step rather than its position because the stored surface is
        not filed against a unit: it is always the step's own, the one word
        the reader is here to learn, so the step has to be on hand to put it
        back where it belongs.
        """
        with open_state(self._path) as conn:
            rows = conn.execute(
                f"SELECT {EXAMPLE_COLUMNS} FROM roadmap_example"
                " WHERE source = ? AND position = ? ORDER BY n",
                (source, step.position)).fetchall()
        return [self._as_sentence(row, step.unit) for row in rows]

    @staticmethod
    def _as_sentence(row, unit: Unit) -> Sentence:
        (_, _, text, translation, origin, surface, units, video_id, start,
         end) = row
        return Sentence(
            text=text,
            origin=origin,
            translation=translation,
            units=frozenset(Unit(kind, key) for kind, key in json.loads(units)),
            surfaces=((unit, surface),) if surface else (),
            # A subtitle row has a duration, but only the start is written
            # down per sentence; falling back to it gives a zero-length span
            # rather than a wrong one, and the player only seeks to the start.
            timing=(Timing(video_id, start, end if end is not None else start)
                    if video_id else None),
        )

    def count(self, source: str = ALL) -> int:
        with open_state(self._path) as conn:
            return conn.execute(
                "SELECT count(*) FROM roadmap WHERE source = ?", (source,)
            ).fetchone()[0]
