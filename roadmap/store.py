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
from datetime import datetime

from state import ensure, open_state

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
#
# 3: strict counting renames a duplicate instead of deleting it. The rule
# runs at load time, so the corpus cache is untouched and the analyser
# fingerprint cannot see the change — but every step of every plan moves,
# and a plan built under the old rule offered sentences holding words it had
# not taught. See `Aliases`.
#
# 4: the judge's level is a factor in a sentence's worth, and a pattern the
# judge says a sentence does not say is dropped from it at load time. Both
# change which sentences reach a deck and which is first, and neither is in
# the analyser fingerprint. See `corpus.answers.Judged`.
#
# 5: a word whose best sentence the judge puts under `FLOOR` is deferred
# until a clean one is a step away, and taught last if none ever is.
ROADMAP_VERSION = 5


def current_stamp(language: str = "de") -> str:
    """What a roadmap built right now would be stamped with.

    The analyser, because a rebuilt corpus holds different sentences and the
    stored decks name theirs by text alone; the quality version, because it
    decides which sentences reach a deck and in what order; and this module's
    own version.
    """
    return (f"{analyser_fingerprint(language)}|{ROADMAP_VERSION}"
            f"|{QUALITY_VERSION}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS roadmap (
    source       TEXT COLLATE "C" NOT NULL DEFAULT 'all',
    position     BIGINT NOT NULL,
    kind         TEXT COLLATE "C" NOT NULL,
    key          TEXT COLLATE "C" NOT NULL,
    sentence     TEXT COLLATE "C" NOT NULL,
    translation  TEXT COLLATE "C",
    origin       TEXT COLLATE "C" NOT NULL,
    surface      TEXT COLLATE "C",
    gain         BIGINT NOT NULL,
    score        DOUBLE PRECISION NOT NULL,
    now_readable BIGINT NOT NULL,
    readable     BIGINT NOT NULL DEFAULT 0,
    occurrences  BIGINT NOT NULL DEFAULT 0,
    -- The word learned alongside this one, on the steps where the walk had to
    -- take two from a sentence because nothing anywhere was one word away.
    -- Null on an ordinary step, which is nearly all of them.
    beside_kind  TEXT COLLATE "C",
    beside_key   TEXT COLLATE "C",
    PRIMARY KEY (source, position)
);

CREATE TABLE IF NOT EXISTS roadmap_example (
    source      TEXT COLLATE "C" NOT NULL,
    position    BIGINT NOT NULL,
    n           BIGINT NOT NULL,
    text        TEXT COLLATE "C" NOT NULL,
    translation TEXT COLLATE "C",
    origin      TEXT COLLATE "C" NOT NULL,
    surface     TEXT COLLATE "C",
    units       TEXT COLLATE "C" NOT NULL,
    video_id    TEXT COLLATE "C",
    start_time  DOUBLE PRECISION,
    end_time    DOUBLE PRECISION,
    PRIMARY KEY (source, position, n)
);

CREATE TABLE IF NOT EXISTS roadmap_meta (
    source  TEXT COLLATE "C" PRIMARY KEY,
    stamp   TEXT COLLATE "C" NOT NULL,
    made_at TEXT COLLATE "C" NOT NULL,
    total   BIGINT NOT NULL DEFAULT 0
);
"""

COLUMNS = ("position, kind, key, sentence, translation, origin, surface,"
           " gain, score, now_readable, readable, occurrences,"
           " beside_kind, beside_key")

EXAMPLE_COLUMNS = ("position, n, text, translation, origin, surface, units,"
                   " video_id, start_time, end_time")


class RoadmapStore:
    def __init__(self, config) -> None:
        self._db = config
        ensure(config, SCHEMA)

    def sources(self) -> dict[str, int]:
        """Which roadmaps exist, and how long each is."""
        with open_state(self._db) as conn:
            return dict(conn.execute(
                "SELECT source, count(*) FROM roadmap GROUP BY source"))

    def stamp(self, source: str = ALL) -> str | None:
        """What this roadmap was built from, or None if nothing was recorded.

        The stored decks name sentences by their text alone, so a roadmap
        outlives the corpus that produced it without any sign of trouble: the
        page keeps serving sentences that may no longer be in the corpus at
        all.  The stamp is how a reader of the store can tell.
        """
        with open_state(self._db) as conn:
            row = conn.execute(
                "SELECT stamp FROM roadmap_meta WHERE source = %s",
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
        with open_state(self._db) as conn:
            row = conn.execute(
                "SELECT total FROM roadmap_meta WHERE source = %s",
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
        with open_state(self._db) as conn:
            conn.execute("DELETE FROM roadmap WHERE source = %s", (source,))
            conn.execute("DELETE FROM roadmap_example WHERE source = %s",
                         (source,))
        self._insert(steps, source, stamp, total)

    def _insert(self, steps: list[RoadmapStep], source: str,
                stamp: str = "", total: int = 0) -> None:
        with open_state(self._db) as conn:
            conn.executemany(
                f"INSERT INTO roadmap (source, {COLUMNS})"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [(source, s.position, s.unit.kind, s.unit.key, s.sentence.text,
                  s.sentence.translation, s.sentence.origin,
                  s.sentence.surface_of(s.unit), s.gain, s.score,
                  s.now_readable, s.readable, s.occurrences,
                  s.beside.kind if s.beside else None,
                  s.beside.key if s.beside else None) for s in steps],
            )
            conn.executemany(
                f"INSERT INTO roadmap_example (source,"
                f" {EXAMPLE_COLUMNS})"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (source, position, n) DO UPDATE SET"
                " text = excluded.text, translation = excluded.translation,"
                " origin = excluded.origin, surface = excluded.surface,"
                " units = excluded.units, video_id = excluded.video_id,"
                " start_time = excluded.start_time, end_time = excluded.end_time",
                [self._example_row(source, step, n, example)
                 for step in steps
                 for n, example in enumerate(step.examples)],
            )
            if stamp:
                conn.execute(
                    "INSERT INTO roadmap_meta"
                    " (source, stamp, made_at, total) VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT (source) DO UPDATE SET stamp = excluded.stamp,"
                    " made_at = excluded.made_at, total = excluded.total",
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

    def labels(self) -> list[str]:
        """Every plan in the store, by the name it was filed under.

        Only ever asked for when a caller has named one that is not there, so
        the answer can be a list of what is.
        """
        with open_state(self._db) as conn:
            return [row[0] for row in conn.execute(
                "SELECT DISTINCT source FROM roadmap ORDER BY source")]

    def load(self, source: str = ALL, limit: int | None = None) -> list[RoadmapStep]:
        """The steps, without their decks.

        The decks are left behind on purpose: the roadmap runs to thousands of
        steps with a couple of dozen sentences each, and every page that wants
        the list wants one line per step.  `deck` fetches the one that is
        actually being read.
        """
        query = (f"SELECT {COLUMNS} FROM roadmap WHERE source = %s ORDER BY position")
        if limit:
            query += f" LIMIT {int(limit)}"
        with open_state(self._db) as conn:
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
                beside=Unit(beside_kind, beside_key) if beside_key else None,
            )
            for (position, kind, key, text, translation, origin, surface, gain,
                 score, now_readable, readable, occurrences,
                 beside_kind, beside_key) in rows
        ]

    def deck(self, source: str, step: RoadmapStep) -> list[Sentence]:
        """The stored deck for one step, in the order the walk ranked it.

        Takes the step rather than its position because the stored surface is
        not filed against a unit: it is always the step's own, the one word
        the reader is here to learn, so the step has to be on hand to put it
        back where it belongs.
        """
        with open_state(self._db) as conn:
            rows = conn.execute(
                f"SELECT {EXAMPLE_COLUMNS} FROM roadmap_example"
                " WHERE source = %s AND position = %s ORDER BY n",
                (source, step.position)).fetchall()
        return [self._as_sentence(row, step.unit) for row in rows]

    def decks(self, source: str, steps: list[RoadmapStep],
              limit: int | None = None) -> dict[int, list[Sentence]]:
        """Every step's deck at once, keyed by position.

        `deck` asks for one because a page shows one. Anything wanting the
        whole plan -- an export, an audio run -- would make several thousand
        queries that way, which is the difference between a second and a
        minute for rows that come off one index in a single pass.

        `limit` is applied per step rather than to the query, since the cap
        is "the first N examples of each" and not "the first N rows".
        """
        by_unit = {step.position: step.unit for step in steps}
        out: dict[int, list[Sentence]] = {}
        with open_state(self._db) as conn:
            rows = conn.execute(
                f"SELECT {EXAMPLE_COLUMNS} FROM roadmap_example"
                " WHERE source = %s ORDER BY position, n", (source,))
            for row in rows:
                # Column order is `position, n, ...` — `n` is the rank of the
                # example within its deck, not the step.
                position = row[0]
                unit = by_unit.get(position)
                if unit is None:
                    continue
                here = out.setdefault(position, [])
                if limit is None or len(here) < limit:
                    here.append(self._as_sentence(row, unit))
        return out

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
        with open_state(self._db) as conn:
            return conn.execute(
                "SELECT count(*) FROM roadmap WHERE source = %s", (source,)
            ).fetchone()[0]
