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
    PRIMARY KEY (source, video_id)
);
CREATE TABLE IF NOT EXISTS video_score_meta (
    source  TEXT PRIMARY KEY,
    stamp   TEXT NOT NULL,
    made_at TEXT NOT NULL
);
"""

COLUMNS = ("video_id", "title", "lines", "minutes", "comprehension",
           "teachable", "teaches", "watch")


class ScoreStore:
    """Scored videos, and the stamp saying who they were scored for."""

    def __init__(self, path: Path) -> None:
        self._path = path
        with open_state(path) as conn:
            conn.executescript(SCHEMA)

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

    def save(self, source: str, stamp: str, rows: list[dict]) -> None:
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM video_score WHERE source = ?", (source,))
            conn.executemany(
                f"INSERT INTO video_score (source, {', '.join(COLUMNS)})"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(source, r["video"], r["title"], r["lines"], r["minutes"],
                  r["comprehension"], r["i+1"], r["teaches"], r["watch"])
                 for r in rows])
            self._restamp(conn, source, stamp)

    def update(self, source: str, stamp: str, rows: list[dict]) -> None:
        """Replace some videos and move the stamp forward.

        The rows not named keep the numbers they had, which is the point:
        they describe videos the change could not have touched.
        """
        with open_state(self._path) as conn:
            conn.executemany(
                f"INSERT INTO video_score (source, {', '.join(COLUMNS)})"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(source, video_id) DO UPDATE SET"
                " title = excluded.title, lines = excluded.lines,"
                " minutes = excluded.minutes,"
                " comprehension = excluded.comprehension,"
                " teachable = excluded.teachable, teaches = excluded.teaches,"
                " watch = excluded.watch",
                [(source, r["video"], r["title"], r["lines"], r["minutes"],
                  r["comprehension"], r["i+1"], r["teaches"], r["watch"])
                 for r in rows])
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
    def _as_row(record) -> dict:
        video, title, lines, minutes, comprehension, teachable, teaches, watch = record
        return {"video": video, "title": title, "lines": lines,
                "minutes": minutes, "comprehension": comprehension,
                "i+1": teachable, "teaches": teaches, "watch": watch}
