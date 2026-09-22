"""Video scores, kept so the app is usable the moment it starts.

Scoring a video means reading its sentences out of the corpus and comparing
every one against what you know — three million unit rows rebuilt into Python
objects, then a pass over a hundred thousand sentences. Held only in memory
that was paid again on every restart, and the pages that want it are the two
you open first.

So the answers live in the database, stamped with what produced them: the
analyser fingerprint, and the version the `known_units` trigger maintains.
Matching stamps mean the numbers still describe you and no corpus is needed
to show them. Mismatched stamps mean they are recomputed — the cache can be
wrong about being fresh in only one direction, and it is the safe one.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from state import open_state

SCHEMA = """
CREATE TABLE IF NOT EXISTS video_score (
    source        TEXT NOT NULL,
    video_id      TEXT NOT NULL,
    title         TEXT,
    lines         INTEGER NOT NULL,
    minutes       REAL,
    comprehension REAL NOT NULL,
    teachable     INTEGER NOT NULL,
    teaches       INTEGER NOT NULL,
    watch         REAL NOT NULL,
    -- The next-best words, as JSON: [[kind, key, sentences unlocked], ...].
    -- A list rather than its own table because it is read whole, written
    -- whole, and never queried across videos.
    next_words    TEXT NOT NULL DEFAULT '[]',
    -- The judge's level of the video, in levels above A1, from a sample of
    -- its lines (`corpus.levels`); NULL until enough of them are levelled.
    level         REAL,
    -- The share of its lines readable whole. `comprehension` is the share
    -- of its words known; the panel's "one word away" arithmetic is in
    -- lines and wants this.
    readable      REAL,
    PRIMARY KEY (source, video_id)
);
CREATE TABLE IF NOT EXISTS video_score_meta (
    source  TEXT PRIMARY KEY,
    stamp   TEXT NOT NULL,
    made_at TEXT NOT NULL
);
"""

COLUMNS = ("video_id", "title", "lines", "minutes", "comprehension",
           "teachable", "teaches", "watch", "next_words", "level", "readable")


class ScoreStore:
    """Scored videos, and the stamp saying who they were scored for."""

    def __init__(self, path: Path) -> None:
        self._path = path
        with open_state(path) as conn:
            conn.executescript(SCHEMA)
            self._add_missing_columns(conn)

    @staticmethod
    def _add_missing_columns(conn) -> None:
        """Bring a table written by an older version up to the current shape.

        `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
        exists, so a new column has to be added by hand or the first write
        fails against a database that predates it.
        """
        have = {row[1] for row in conn.execute("PRAGMA table_info(video_score)")}
        if "next_words" not in have:
            conn.execute("ALTER TABLE video_score ADD COLUMN"
                         " next_words TEXT NOT NULL DEFAULT '[]'")
        if "level" not in have:
            conn.execute("ALTER TABLE video_score ADD COLUMN level REAL")
        if "readable" not in have:
            conn.execute("ALTER TABLE video_score ADD COLUMN readable REAL")

    def load(self, source: str, stamp: str) -> list[dict] | None:
        """The stored scores, or None if they no longer describe you."""
        with open_state(self._path) as conn:
            row = conn.execute("SELECT stamp FROM video_score_meta WHERE source = ?",
                               (source,)).fetchone()
            if not row or row[0] != stamp:
                return None
            rows = conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM video_score WHERE source = ?"
                " ORDER BY watch DESC", (source,)).fetchall()
        return [self._as_row(r) for r in rows]

    def stamp(self, source: str) -> str | None:
        """What the stored rows were computed against, or None if there are
        none. `load` answers the question a page asks — do these still
        describe the reader — and refuses anything else. This answers the
        narrower one an incremental repair has to ask first: *why* they no
        longer match. Rows left behind by a word being marked can be patched
        and restamped; rows left behind by a rebuilt corpus cannot, and
        restamping those would declare every untouched video fresh under an
        analyser that never scored it.
        """
        with open_state(self._path) as conn:
            row = conn.execute("SELECT stamp FROM video_score_meta WHERE source = ?",
                               (source,)).fetchone()
        return row[0] if row else None

    def latest(self, source: str | None = None) -> list[dict]:
        """The stored scores as last written, best first, whoever they were
        scored for. Not for a page -- `load` is, and it refuses a stamp
        that no longer describes the reader -- but for choosing which
        videos to spend on first: the reel's order moves with every word
        learned, and slowly, so the last order is the right one to work
        down. With no `source` named, the source scored most recently --
        the one the reel was last looked at under."""
        with open_state(self._path) as conn:
            if source is None:
                row = conn.execute("SELECT source FROM video_score_meta"
                                   " ORDER BY made_at DESC LIMIT 1").fetchone()
                if row is None:
                    return []
                source = row[0]
            rows = conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM video_score WHERE source = ?"
                " ORDER BY watch DESC", (source,)).fetchall()
        return [self._as_row(r) for r in rows]

    def save(self, source: str, stamp: str, rows: list[dict]) -> None:
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM video_score WHERE source = ?", (source,))
            conn.executemany(
                f"INSERT INTO video_score (source, {', '.join(COLUMNS)})"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [self._as_record(source, r) for r in rows])
            self._restamp(conn, source, stamp)

    def update(self, source: str, stamp: str, rows: list[dict]) -> None:
        """Replace some videos and move the stamp forward.

        The rows not named keep the numbers they had, which is the point:
        they describe videos the change could not have touched.
        """
        with open_state(self._path) as conn:
            conn.executemany(
                f"INSERT INTO video_score (source, {', '.join(COLUMNS)})"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(source, video_id) DO UPDATE SET"
                " title = excluded.title, lines = excluded.lines,"
                " minutes = excluded.minutes,"
                " comprehension = excluded.comprehension,"
                " teachable = excluded.teachable, teaches = excluded.teaches,"
                " watch = excluded.watch, next_words = excluded.next_words,"
                " level = excluded.level, readable = excluded.readable",
                [self._as_record(source, r) for r in rows])
            self._restamp(conn, source, stamp)

    def restamp(self, source: str, stamp: str) -> None:
        """Say the stored rows describe this state after all.

        Used when a change provably touched none of them — a word no video
        says. Without it the stamp would stay behind and the next read would
        rebuild nine hundred rows to arrive at what is already there.
        """
        with open_state(self._path) as conn:
            self._restamp(conn, source, stamp)

    @staticmethod
    def _restamp(conn, source: str, stamp: str) -> None:
        conn.execute(
            "INSERT INTO video_score_meta (source, stamp, made_at)"
            " VALUES (?, ?, ?) ON CONFLICT(source) DO UPDATE SET"
            " stamp = excluded.stamp, made_at = excluded.made_at",
            (source, stamp, datetime.now().isoformat(timespec="seconds")))

    @staticmethod
    def _as_record(source: str, row: dict) -> tuple:
        return (source, row["video"], row["title"], row["lines"], row["minutes"],
                row["comprehension"], row["i+1"], row["teaches"], row["watch"],
                json.dumps(row.get("next", []), ensure_ascii=False), row.get("level"),
                row.get("readable"))

    @staticmethod
    def _as_row(record) -> dict:
        (video, title, lines, minutes, comprehension, teachable, teaches,
         watch, next_words, level, readable) = record
        return {"video": video, "title": title, "lines": lines,
                "minutes": minutes, "comprehension": comprehension,
                "i+1": teachable, "teaches": teaches, "watch": watch,
                "next": [tuple(x) for x in json.loads(next_words)],
                "level": level, "readable": readable}
