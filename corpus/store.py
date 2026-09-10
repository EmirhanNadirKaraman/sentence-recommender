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

from fingerprint import analyser_fingerprint, packages_fingerprint
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
-- One video's cues, for the transcript beside the player. Without this
-- the only way to that answer is a scan of every sentence in the table.
CREATE INDEX IF NOT EXISTS ix_sentences_video ON sentences(video_id);
CREATE TABLE IF NOT EXISTS sentence_units (
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    surface     TEXT
);
CREATE INDEX IF NOT EXISTS ix_units_sentence ON sentence_units(sentence_id);
-- Sentences that say a given word. Without it the only way to that answer is
-- a scan of 1.18M rows, which is why the pages wanting it used to load the
-- entire corpus into memory instead.
--
-- `sentence_id` is in the index rather than fetched from the row it points
-- at, which is the whole answer the `holding` subquery wants: for a word like
-- `sein`, said in 35,192 sentences, that is 35,192 row reads the query no
-- longer does.
CREATE INDEX IF NOT EXISTS ix_units_key ON sentence_units(kind, key, sentence_id);
CREATE TABLE IF NOT EXISTS build_meta (
    build       TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    made_at     TEXT NOT NULL,
    -- The parser that produced it, kept apart from the rules hash: a
    -- different spaCy is worth saying out loud, but it is not a reason for a
    -- machine that only serves these rows to distrust them.
    packages    TEXT NOT NULL DEFAULT ''
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
        meta = {row[1] for row in conn.execute("PRAGMA table_info(build_meta)")}
        if "packages" not in meta:
            conn.execute("ALTER TABLE build_meta ADD COLUMN packages"
                         " TEXT NOT NULL DEFAULT ''")
        # An index is created IF NOT EXISTS, so widening one in `SCHEMA` does
        # nothing to a file that already has the narrow version — it has to be
        # dropped. Guarded on the stored definition rather than a version
        # number, so it runs once and is a no-op forever after.
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'index'"
                           " AND name = 'ix_units_key'").fetchone()
        if row and "sentence_id" not in (row[0] or ""):
            conn.execute("DROP INDEX ix_units_key")
            conn.execute("CREATE INDEX ix_units_key"
                         " ON sentence_units(kind, key, sentence_id)")

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

    def parser_changed(self) -> dict[str, str]:
        """Builds analysed by a different spaCy than the one installed here.

        Worth a word — the parser decides what a lemma is — but not a reason
        to throw the build away, and emphatically not a reason for a host that
        never parses anything to call every cache stale. Builds with nothing
        recorded are skipped rather than reported: they predate this column,
        and warning about every one of them would be noise.
        """
        now = packages_fingerprint()
        with self._connect() as conn:
            stored = dict(conn.execute(
                "SELECT build, packages FROM build_meta"))
        return {b: stored[b] for b in self.builds()
                if stored.get(b) and stored[b] != now}

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
                "INSERT INTO build_meta (build, fingerprint, made_at, packages)"
                " VALUES (?, ?, ?, ?) ON CONFLICT(build) DO UPDATE SET"
                " fingerprint = excluded.fingerprint, made_at = excluded.made_at,"
                " packages = excluded.packages",
                (build, analyser_fingerprint(),
                 datetime.now().isoformat(timespec="seconds"),
                 packages_fingerprint()),
            )
            # Table statistics, refreshed whenever a build changes the data
            # they describe. Stale ones are worse than none: the planner
            # believes them. Seven tenths of a second at the end of a build
            # that takes minutes.
            conn.execute("ANALYZE")

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

    def unit_counts(self, *builds: str) -> "Counter":
        """How often each unit is said, counted by the database.

        The alternative is materialising every sentence and tallying the units
        in Python, which is nineteen seconds to answer a question SQLite can
        answer from an index. Corrections are not applied — a hidden sentence
        still counts here — because this ranks what to ask about first and a
        handful of rows cannot change that order.
        """
        from collections import Counter
        if not builds:
            return Counter()
        # The join exists only to filter by build. When the builds asked for
        # are every build there is, it filters nothing and costs everything —
        # 1.18M unit rows walked against the sentence table to reach an answer
        # `ix_units_key` can give on its own.
        everything = set(builds) >= set(self.builds())
        placeholders = ",".join("?" * len(builds))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, key, count(*) FROM sentence_units"
                " GROUP BY kind, key") if everything else conn.execute(
                "SELECT su.kind, su.key, count(*) FROM sentence_units su"
                " JOIN sentences s ON s.id = su.sentence_id"
                f" WHERE s.build IN ({placeholders})"
                " GROUP BY su.kind, su.key", builds)
            return Counter({(kind, key): n for kind, key, n in rows})

    def example_texts(self, kind: str, key: str, *builds: str,
                      words: tuple[int, int] | None = None,
                      limit: int = 40) -> list[str]:
        """Texts of sentences saying one unit — the text, and nothing else.

        `load(holding=...)` answers the same question properly: it returns
        Sentence objects with their unit sets, which is what a word's page
        needs to say how many unknowns each one carries. Picking an example
        needs none of that. `corpus.quality.score` reads the string, so the
        unit join — 35,192 sentences and roughly 420,000 unit rows for a word
        like `sein` — is built, interned, and thrown away unread. It was ten
        seconds before every question in the quiz, on a warm cache less, and
        the whole of it went on data the caller never looked at.

        `words` narrows to a range of word counts, which is what makes this
        cheap rather than merely cheaper: with a limit, the database stops as
        soon as it has enough and never visits the other thirty thousand. The
        count is approximate — SQLite has no `split`, so runs of spaces read
        as extra words — which is why this returns candidates rather than a
        winner. SQL narrows; the caller scores what comes back.
        """
        if not builds:
            return []
        placeholders = ",".join("?" * len(builds))
        # `length(x) - length(replace(x, ' ', ''))` is the number of spaces.
        counted = " AND length(text) - length(replace(text, ' ', '')) + 1" \
                  " BETWEEN ? AND ?" if words else ""
        args = builds + (kind, key) + (tuple(words) if words else ()) + (limit,)
        with self._connect() as conn:
            return [text for (text,) in conn.execute(
                f"SELECT text FROM sentences WHERE build IN ({placeholders})"
                " AND teachable = 1"
                " AND id IN (SELECT sentence_id FROM sentence_units"
                "            WHERE kind = ? AND key = ?)"
                f"{counted} LIMIT ?", args)]

    def load(self, *builds: str, teachable_only: bool = True,
             video: str | None = None,
             holding: tuple[str, str] | None = None,
             text: str | None = None) -> list[Sentence]:
        """Cached sentences.  By default only the ones worth studying from —
        pass `teachable_only=False` for the full transcript, which is what an
        overlay needs.

        `holding` narrows to the sentences containing one unit, given as
        `(kind, key)` — what a word's own page wants, and the only thing it
        wants. It used to get there by loading every sentence of the corpus
        and keeping the twenty-five that said the word.

        `text` narrows to one sentence, which is what the correction page
        wants — it was finding it by walking every sentence in memory.

        `video` narrows to one video's lines, which is what the transcript
        panel wants and the only thing it wants. Asked without it, that panel
        loaded every sentence of every build to keep the two hundred it
        needed — a scan of the whole table, plus its million-odd unit rows,
        interned into Python objects and then thrown away. Pushing the filter
        into SQL is the difference between a page and a coffee.
        """
        if not builds:
            return []          # `WHERE build IN ()` is not valid SQL
        placeholders = ",".join("?" * len(builds))
        teachable = " AND teachable = 1" if teachable_only else ""
        # Narrowing both halves matters: the unit join is the larger of the
        # two, and filtering only the sentences would still walk every unit
        # row in the corpus to find the handful belonging to this video.
        one_video = " AND video_id = ?" if video else ""
        joined_video = " AND s.video_id = ?" if video else ""
        # A subquery rather than a join, so the sentence rows come back once:
        # a sentence can hold the same unit twice and a join would duplicate
        # it.
        said_here = (" AND id IN (SELECT sentence_id FROM sentence_units"
                     " WHERE kind = ? AND key = ?)" if holding else "")
        joined_here = (" AND s.id IN (SELECT sentence_id FROM sentence_units"
                       " WHERE kind = ? AND key = ?)" if holding else "")
        one_text = " AND text = ?" if text else ""
        joined_text = " AND s.text = ?" if text else ""
        args = (builds + ((video,) if video else ()) + (holding or ())
                + ((text,) if text else ()))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, origin, text, translation, raw_text, source_ids,"
                " video_id, start_time, end_time, teachable"
                f" FROM sentences WHERE build IN ({placeholders}){teachable}"
                f"{one_video}{said_here}{one_text}", args,
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
                f" WHERE s.build IN ({placeholders}){joined_video}"
                f"{joined_here}{joined_text}", args,
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
