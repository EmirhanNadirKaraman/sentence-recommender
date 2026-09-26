"""The assembled corpus, in Postgres.

Analysing the corpus costs real time — a couple of minutes for the subtitles
— and none of it depends on anything the reader does between runs. So the
result is stored and rebuilt only when asked.

Rows are keyed by `build`, a label naming both the source and how it was
assembled (`subtitle`, `subtitle:llm`). Without that key one way of
assembling the subtitles would overwrite another.

This lived in SQLite until the project had a Postgres database of its own.
It moved because of one query: subtracting what the reader knows from what a
sentence holds, 3.48M times per load, in Python, against a set. In SQL over
the same data that is 2.18s where Python takes 10.04s, and it agrees on all
169,155 sentences.

The tables are `corpus_sentence` and `corpus_unit` rather than `sentences`
and `sentence_units`, because the catalogue already has a `sentence` — the
raw caption rows as scraped. These are what was reassembled and analysed out
of those, and a quarter of them span several. Two names one letter apart for
things that different would not have survived contact.

The schema is alembic's, not this file's. There is no `CREATE TABLE` here and
no migration code: a database that has not been migrated says so when a query
fails, which is better than a half-built schema created on the fly.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

from alignment.timing import Timing
from corpus.sentence import Sentence
from fingerprint import analyser_fingerprint, packages_fingerprint
from vocab.entry import Unit

# How many sentences go in one INSERT. Large enough that the round trips
# disappear, small enough that the returned ids and their unit rows do not
# have to be held all at once.
BATCH = 5_000


class CorpusStore:
    """Reads and writes stored corpus builds."""

    def __init__(self, config, ignored: frozenset[str] = frozenset()) -> None:
        self._config = config
        # Builds that exist but are not studied from. Hidden here rather than
        # deleted, so the rows survive and one setting brings them back.
        # `load` still returns them if asked by name — only the "every build"
        # default and the source picker skip them.
        self._ignored = ignored
        self._connection = None

    def _conn(self):
        """One connection for the life of the store.

        `CorpusStore` is a cached property of the application, so this is one
        connection per process. Opening a fresh one per call cost nothing in
        SQLite and costs a round trip here, on methods that pages call several
        times each.
        """
        if self._connection is None or self._connection.closed:
            self._connection = psycopg2.connect(**self._config.dsn_kwargs())
            self._connection.autocommit = True
        return self._connection

    @contextmanager
    def _read(self):
        with self._conn().cursor() as cur:
            yield cur

    @contextmanager
    def _write_txn(self):
        """A write that lands whole or not at all.

        Rebuilding a build deletes what is there and writes what replaces it;
        a failure between the two would leave the corpus empty with no way to
        tell that it had ever been otherwise.
        """
        conn = self._conn()
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.autocommit = True

    # ---- what is here -----------------------------------------------------

    def builds(self, teachable_only: bool = False) -> dict[str, int]:
        """Build name -> how many sentences it holds.

        `teachable_only` counts what the roadmap can actually use, leaving out
        the rows a subtitle build keeps purely so the overlay has no gaps.
        """
        where = " WHERE teachable" if teachable_only else ""
        with self._read() as cur:
            cur.execute(f"SELECT build, count(*) FROM corpus_sentence{where}"
                        " GROUP BY build")
            return {b: n for b, n in cur.fetchall() if b not in self._ignored}

    def lemma_keys(self) -> set[str]:
        """Every lemma the cached corpus uses, once each.

        Read from `corpus_unit_count` rather than `corpus_unit`: the
        aggregate holds one row per unit per build, tens of thousands, where
        the raw table holds one per occurrence and runs to millions. The
        question here is only which lemmas exist, and the aggregate answers
        it without a scan.
        """
        with self._read() as cur:
            cur.execute("SELECT DISTINCT build, key FROM corpus_unit_count"
                        " WHERE kind = 'lemma'")
            return {key for build, key in cur.fetchall()
                    if build not in self._ignored}

    def lines_per_video(self, *builds: str) -> dict[str, int]:
        """Every line a video's subtitles hold, kept or dropped.

        A count rather than the rows: the filtered-out lines are wanted only
        as a denominator, and loading a hundred and thirty-five thousand of
        them to take their length would cost more than everything that uses
        the answer.
        """
        with self._read() as cur:
            cur.execute("SELECT video_id, count(*) FROM corpus_sentence"
                        " WHERE build = ANY(%s) AND video_id IS NOT NULL"
                        " GROUP BY video_id",
                        (list(builds) or list(self.builds()),))
            return {video: n for video, n in cur.fetchall()}

    def video_ids(self, build: str) -> set[str]:
        """Which videos a build already holds, so the rest can be skipped."""
        with self._read() as cur:
            cur.execute("SELECT DISTINCT video_id FROM corpus_sentence"
                        " WHERE build = %s AND video_id IS NOT NULL", (build,))
            return {row[0] for row in cur.fetchall()}

    def parser_changed(self) -> dict[str, str]:
        """Builds analysed by a different spaCy than the one installed here.

        Worth a word — the parser decides what a lemma is — but not a reason
        to throw the build away, and emphatically not a reason for a host that
        never parses anything to call every cache stale. Builds with nothing
        recorded are skipped rather than reported: they predate this column,
        and warning about every one of them would be noise.
        """
        now = packages_fingerprint()
        with self._read() as cur:
            cur.execute("SELECT build, packages FROM build_meta")
            stored = dict(cur.fetchall())
        return {b: stored[b] for b in self.builds()
                if stored.get(b) and stored[b] != now}

    def stale(self) -> dict[str, str]:
        """Builds whose fingerprint no longer matches the rules in force.

        Name -> the fingerprint it was made with. A build with no record at
        all counts as stale: it predates this bookkeeping, so nothing can
        vouch for it.
        """
        now = analyser_fingerprint()
        with self._read() as cur:
            cur.execute("SELECT build, fingerprint FROM build_meta")
            stored = dict(cur.fetchall())
        return {b: stored.get(b, "unrecorded") for b in self.builds()
                if stored.get(b) != now}

    def vintage(self) -> str:
        """What state the corpus is in, as one short string.

        The highest sentence id, and when each build was last stamped. Anything
        holding answers read off the corpus compares this and throws them away
        when it changes; `stale` asks the different question of whether a build
        was made under the rules in force.

        The id is there because the stamps are not enough. `append` stamps the
        build it writes, and yet this table has held sentences written by later
        transactions than the one that last wrote `build_meta` — so something
        appends without stamping, and the video that arrived that way sat in
        the corpus unscored and missing from every ranked list in the app. The
        id cannot be skipped by anyone: the sequence only goes up, so it moves
        whenever a row is inserted, whoever inserts it and whatever else they
        forget. A rebuild that replaces every row moves it too.

        One round trip, and `max(id)` is an index-only read of the primary key.
        Per-build ids would be better still and cost twenty times as much —
        measured at 134ms against 8 — for a distinction nothing here draws.
        """
        with self._read() as cur:
            cur.execute("SELECT (SELECT max(id) FROM corpus_sentence),"
                        " (SELECT string_agg(build || ':' || made_at, ','"
                        "  ORDER BY build) FROM build_meta)")
            top, stamps = cur.fetchone()
        return f"{top or 0}/{stamps or '-'}"

    # ---- writing ----------------------------------------------------------

    def append(self, sentences: list[Sentence], build: str) -> None:
        """Add to a build without disturbing what is already in it."""
        self._write(sentences, build)
        self._stamp(build)

    def save(self, sentences: list[Sentence], build: str) -> None:
        # What a detector said survives the rebuild. `language` is filled by
        # `detect-language` after a build, and a rebuild that reinserts the
        # rows forgot it: four rebuilds on 2026-09-20 wiped 12,649 English
        # marks, and the next walk put `Why did I stand in the pillory?` on
        # a card. Kept by text, which is what the detector read.
        with self._read() as cur:
            cur.execute("SELECT text, language FROM corpus_sentence"
                        " WHERE build = %s AND language IS NOT NULL", (build,))
            said = dict(cur.fetchall())
        with self._write_txn() as cur:
            # The foreign key cascades, so the units go with their sentences
            # and there is no second DELETE to get wrong.
            cur.execute("DELETE FROM corpus_sentence WHERE build = %s", (build,))
        self._write(sentences, build)
        kept = [(build, s.text, said[s.text]) for s in sentences if s.text in said]
        if kept:
            with self._write_txn() as cur:
                execute_values(
                    cur,
                    "UPDATE corpus_sentence AS s SET language = v.language"
                    " FROM (VALUES %s) AS v (build, text, language)"
                    " WHERE s.build = v.build AND s.text = v.text",
                    kept, template="(%s, %s, %s)", page_size=5000)
        self._stamp(build)

    def append(self, sentences: list[Sentence], build: str) -> None:
        """Add to a build what `save` would have replaced it with.

        For the sentences a reader writes (`vocab.own_sentences`): one at a
        time, into the `generated` build beside the model's, and the build
        stays what it was otherwise. A text the build already holds is left
        alone rather than doubled.
        """
        with self._read() as cur:
            cur.execute("SELECT text FROM corpus_sentence WHERE build = %s AND text = ANY(%s)",
                        (build, [s.text for s in sentences]))
            held = {text for (text,) in cur.fetchall()}
        fresh = [s for s in sentences if s.text not in held]
        if fresh:
            self._write(fresh, build)
            with self._read() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY corpus_unit_count")

    def _write(self, sentences: list[Sentence], build: str) -> None:
        """Insert sentences and their units, in batches.

        The ids come back from the INSERT rather than being read afterwards:
        `execute_values(..., fetch=True)` returns them in the order the rows
        were given, which is what pairs each sentence with its own units.
        """
        with self._write_txn() as cur:
            for start in range(0, len(sentences), BATCH):
                chunk = sentences[start:start + BATCH]
                rows = [
                    (build, s.origin, s.text, s.translation, s.raw_text,
                     ",".join(str(i) for i in s.source_ids),
                     *self._timing_row(s), bool(s.teachable))
                    for s in chunk
                ]
                ids = execute_values(
                    cur,
                    "INSERT INTO corpus_sentence (build, origin, text,"
                    " translation, raw_text, source_ids, video_id, start_time,"
                    " end_time, teachable) VALUES %s RETURNING id",
                    rows, fetch=True)
                units = [
                    (sid, u.kind, u.key, s.surface_of(u))
                    for (sid,), s in zip(ids, chunk)
                    for u in s.units
                ]
                if units:
                    execute_values(
                        cur,
                        "INSERT INTO corpus_unit (sentence_id, kind, key,"
                        " surface) VALUES %s", units, page_size=10_000)

    @staticmethod
    def _timing_row(sentence: Sentence) -> tuple:
        timing = sentence.timing
        return ((timing.video_id, timing.start, timing.end) if timing
                else (None, None, None))

    def _stamp(self, build: str) -> None:
        with self._write_txn() as cur:
            cur.execute(
                "INSERT INTO build_meta (build, fingerprint, made_at, packages)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (build) DO UPDATE SET"
                " fingerprint = excluded.fingerprint,"
                " made_at = excluded.made_at, packages = excluded.packages",
                (build, analyser_fingerprint(),
                 datetime.now().isoformat(timespec="seconds"),
                 packages_fingerprint()))
        # Outside the transaction: neither of these can run inside one.
        # CONCURRENTLY so a rebuild does not lock out whatever is reading.
        with self._read() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY"
                        " corpus_unit_count")
            # Statistics, refreshed where the data has just changed. Stale
            # ones are worse than none: the planner believes them.
            cur.execute("ANALYZE corpus_sentence")
            cur.execute("ANALYZE corpus_unit")

    # ---- reading ----------------------------------------------------------

    def untranslated(self) -> list[tuple[str, bool]]:
        """Every distinct sentence no build holds an English line for.

        (text, teachable) pairs, teachable ones first and each group in the
        order the corpus was written. One sentence can sit in several builds
        -- the same caption in `subtitle` and `transcript`, say -- and it
        counts as translated if any of them has it, since what is asked for
        is the English of the text, not of the row.

        Teachable is likewise any-of. The rows a build keeps only so the
        overlay has no gaps are the same text as a teachable row often
        enough that the two would otherwise be asked about twice.
        """
        with self._read() as cur:
            cur.execute(
                "SELECT text, bool_or(teachable) AS teachable"
                " FROM corpus_sentence"
                " WHERE NOT (build = ANY(%s))"
                " GROUP BY text"
                " HAVING NOT bool_or(coalesce(translation, '') <> '')"
                " ORDER BY bool_or(teachable) DESC, min(id)",
                (sorted(self._ignored),))
            return [(text, bool(teachable)) for text, teachable in cur]

    def unit_counts(self, *builds: str) -> Counter:
        """How often each unit is said.

        Off the materialized view, which is 59ms where grouping the 1.74M unit
        rows live is 197ms. Corrections are not applied — a hidden sentence
        still counts here — because this ranks what to ask about first and a
        handful of rows cannot change that order.
        """
        if not builds:
            return Counter()
        with self._read() as cur:
            cur.execute("SELECT kind, key, sum(said)::int FROM corpus_unit_count"
                        " WHERE build = ANY(%s) GROUP BY kind, key",
                        (list(builds),))
            return Counter({(kind, key): n for kind, key, n in cur.fetchall()})

    def example_texts(self, kind: str, key: str, *builds: str,
                      words: tuple[int, int] | None = None,
                      limit: int = 40) -> list[str]:
        """Texts of sentences saying one unit — the text, and nothing else.

        `load(holding=...)` answers the same question properly: it returns
        Sentence objects with their unit sets, which is what a word's page
        needs to say how many unknowns each one carries. Picking an example
        needs none of that, and building it was ten seconds before every
        question in the quiz, all of it on data the caller never looked at.
        """
        if not builds:
            return []
        # `length(x) - length(replace(x, ' ', ''))` is the number of spaces.
        counted = (" AND length(text) - length(replace(text, ' ', '')) + 1"
                   " BETWEEN %s AND %s" if words else "")
        args = ([list(builds), kind, key]
                + (list(words) if words else []) + [limit])
        with self._read() as cur:
            cur.execute(
                "SELECT text FROM corpus_sentence WHERE build = ANY(%s)"
                " AND teachable"
                " AND id IN (SELECT sentence_id FROM corpus_unit"
                "            WHERE kind = %s AND key = %s)"
                f"{counted} LIMIT %s", args)
            return [text for (text,) in cur.fetchall()]

    def load(self, *builds: str, teachable_only: bool = True,
             video: str | None = None,
             holding: tuple[str, str] | None = None,
             text: str | None = None,
             resolve=None,
             german_only: bool = True) -> list[Sentence]:
        """Stored sentences. By default only the ones worth studying from —
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
        needed.

        `keep` decides which units survive — `Application.corpus` passes the
        rule that strict and list counting each want. It belongs here rather
        than in a pass afterwards because a pass afterwards has to rebuild
        every sentence it touches: 169,155 objects thrown away and 169,155
        made, each with a fresh frozenset and tuple, to drop a few units from
        some of them. That rebuild was 3.35 of the 7.7 seconds a cold
        `/blocked` cost, and none of it was the test itself.
        """
        if not builds:
            return []          # `= ANY('{}')` matches nothing, but say so here
        teachable = " AND teachable" if teachable_only else ""
        # English sentences are kept in the corpus and skipped by everything
        # that learns from it. The transcripts are bilingual, and 5,228 of
        # these rows are English — two of them were teaching steps 5 and 20
        # of the beginner roadmap. They stay because they were still *said*,
        # and the overlay is assembled from everything said; `german_only=
        # False` is how the overlay asks for them.
        #
        # `IS NULL` is kept, and that is the whole reason this is safe to add
        # to a corpus already built: NULL means nobody has looked, which is
        # not the same as not-German. A build that has never run
        # `detect-language` loads exactly as it did before.
        german = (" AND (language IS NULL OR language = 'de')"
                  if german_only else "")
        joined_german = (" AND (s.language IS NULL OR s.language = 'de')"
                         if german_only else "")
        # Narrowing both halves matters: the unit join is the larger of the
        # two, and filtering only the sentences would still walk every unit
        # row in the corpus to find the handful belonging to this video.
        one_video = " AND video_id = %s" if video else ""
        joined_video = " AND s.video_id = %s" if video else ""
        # A subquery rather than a join, so the sentence rows come back once:
        # a sentence can hold the same unit twice and a join would duplicate
        # it.
        said_here = (" AND id IN (SELECT sentence_id FROM corpus_unit"
                     " WHERE kind = %s AND key = %s)" if holding else "")
        joined_here = (" AND s.id IN (SELECT sentence_id FROM corpus_unit"
                       " WHERE kind = %s AND key = %s)" if holding else "")
        one_text = " AND text = %s" if text else ""
        joined_text = " AND s.text = %s" if text else ""
        args = ([list(builds)] + ([video] if video else [])
                + (list(holding) if holding else []) + ([text] if text else []))
        with self._read() as cur:
            cur.execute(
                "SELECT id, origin, text, translation, raw_text, source_ids,"
                " video_id, start_time, end_time, teachable"
                f" FROM corpus_sentence WHERE build = ANY(%s){teachable}"
                f"{german}{one_video}{said_here}{one_text}", args)
            rows = cur.fetchall()
            units: dict[int, set[Unit]] = {}
            surfaces: dict[int, list[tuple[Unit, str]]] = {}
            # Two million unit rows across forty thousand distinct units, so
            # nearly every one is a repeat. Interning them turns most of those
            # rows into a dict lookup instead of an object, which is most of
            # the cost of loading a large corpus.
            # (kind, key) -> the unit that stands for it, or None where
            # `resolve` dropped it. The verdict depends on the unit alone, so
            # it is reached once per distinct unit rather than once per row —
            # 46,433 decisions instead of 1,742,479. That is also why strict
            # counting renames a duplicate rather than deciding per sentence
            # whether the goal that covers it is nearby: the rename needs
            # nothing but the unit, so it keeps this.
            seen: dict[tuple[str, str], Unit | None] = {}
            unseen = object()          # None already means "refused"
            cur.execute(
                "SELECT su.sentence_id, su.kind, su.key, su.surface"
                " FROM corpus_unit su"
                " JOIN corpus_sentence s ON s.id = su.sentence_id"
                f" WHERE s.build = ANY(%s){joined_german}{joined_video}"
                f"{joined_here}{joined_text}", args)
            for sid, kind, key, surface in cur:
                unit = seen.get((kind, key), unseen)
                if unit is unseen:
                    made = Unit(kind, key)
                    unit = seen[(kind, key)] = (
                        made if resolve is None else resolve(made))
                if unit is None:
                    continue
                units.setdefault(sid, set()).add(unit)
                if surface:
                    surfaces.setdefault(sid, []).append((unit, surface))
        return [
            Sentence(
                text=text_,
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
            for sid, origin, text_, translation, raw_text, source_ids,
                video_id, start_time, end_time, teachable_flag in rows
        ]
