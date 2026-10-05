"""Reader corrections to what the analyser decided.

The analyser is right most of the time and wrong in ways no threshold catches:
a sentence that is nonsense out of context, a word it split badly, a pattern
it invented. Three corrections are possible here — hide the sentence, say
what its units actually are, or mark how good it is — and all of them outrank
whatever the analyser thought.

The third is the quiet one. `corpus.quality.score` reads a sentence's length
and how many of its words are distinct, and ranks examples on that already.
What it cannot see is that `Du hast studiert, also wo die Verlet
zurückgetreten ist` is a transcription error: the sentence is an ordinary
length with ordinary variety, and nothing computable from its characters
says `Verlet` is not a German word. That judgement comes from outside the
text — from a reader, or from a model asked to translate it and declining.

Keyed by sentence text rather than row id. The corpus is rebuilt from scratch
whenever the analyser changes, and ids change with it; a correction that
vanished on the next rebuild would be worse than no correction at all.
"""
from __future__ import annotations


from state import ensure, open_state
from datetime import datetime

from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS hidden_sentences (
    text     TEXT COLLATE "C" PRIMARY KEY,
    hidden   TEXT COLLATE "C" NOT NULL
);
-- Sentences the reader liked. Not a verdict and not a hiding: those two say
-- whether a sentence is a good example, and this says nothing about quality
-- at all. It is a bookmark, so nothing ranks on it and nothing filters by it.
CREATE TABLE IF NOT EXISTS starred_sentences (
    text     TEXT COLLATE "C" PRIMARY KEY,
    starred  TEXT COLLATE "C" NOT NULL
);
-- Words waiting to be written out as Anki cards. A word rather than a
-- sentence, because the card is the word and the sentences are what it
-- means: one card carries three of them with the word blanked out, which
-- is the review this deck exists for and is not a thing to make by hand.
CREATE TABLE IF NOT EXISTS anki_words (
    kind   TEXT COLLATE "C" NOT NULL,
    key    TEXT COLLATE "C" NOT NULL,
    queued TEXT COLLATE "C" NOT NULL,
    -- When the word last went into a file the reader can import. Per word
    -- rather than one "last exported" time: a word can be queued, exported,
    -- taken out and put back, and a single timestamp compared against
    -- `queued` would call that word old.
    exported TEXT COLLATE "C",
    PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS sentence_units_override (
    text     TEXT COLLATE "C" NOT NULL,
    kind     TEXT COLLATE "C" NOT NULL,
    key      TEXT COLLATE "C" NOT NULL,
    surface  TEXT COLLATE "C",
    PRIMARY KEY (text, kind, key)
);
CREATE TABLE IF NOT EXISTS corrected_sentences (
    text      TEXT COLLATE "C" PRIMARY KEY,
    corrected TEXT COLLATE "C" NOT NULL
);
-- 0 to 1, higher is better. Absent means no opinion, which is not the same
-- as a middling one: a sentence nobody has judged should rank on its own
-- merits rather than be penalised for going unread.
CREATE TABLE IF NOT EXISTS sentence_verdict (
    text     TEXT COLLATE "C" NOT NULL,
    verdict  DOUBLE PRECISION NOT NULL,
    source   TEXT COLLATE "C" NOT NULL,
    made_at  TEXT COLLATE "C" NOT NULL,
    PRIMARY KEY (text, source)
);
"""


# Who said so. A reader is a person looking at the sentence; everything else
# is a pass that judged it without one.
READER = "reader"


class SentenceOverrides:
    """What the reader has said about particular sentences."""

    def __init__(self, config) -> None:
        self._db = config
        ensure(config, SCHEMA)

    # --- hiding ----------------------------------------------------------

    def hide(self, text: str) -> None:
        with open_state(self._db) as conn:
            conn.execute(
                "INSERT INTO hidden_sentences (text, hidden)"
                " VALUES (%s, %s) ON CONFLICT DO NOTHING", (text, datetime.now().isoformat()))

    def show(self, text: str) -> None:
        with open_state(self._db) as conn:
            conn.execute("DELETE FROM hidden_sentences WHERE text = %s", (text,))

    def hidden(self) -> set[str]:
        with open_state(self._db) as conn:
            return {row[0] for row in
                    conn.execute("SELECT text FROM hidden_sentences")}

    # --- keeping one ------------------------------------------------------

    def star(self, text: str) -> None:
        """Keep a sentence to come back to. Starring one already starred
        changes nothing, not even the date, so the list keeps its order."""
        with open_state(self._db) as conn:
            conn.execute(
                "INSERT INTO starred_sentences (text, starred)"
                " VALUES (%s, %s) ON CONFLICT DO NOTHING", (text, datetime.now().isoformat()))

    def unstar(self, text: str) -> None:
        with open_state(self._db) as conn:
            conn.execute("DELETE FROM starred_sentences WHERE text = %s", (text,))

    def starred(self) -> dict[str, str]:
        """Text -> when it was starred, newest first."""
        with open_state(self._db) as conn:
            return {row[0]: row[1] for row in conn.execute(
                "SELECT text, starred FROM starred_sentences"
                " ORDER BY starred DESC, text")}

    # --- words waiting for Anki -------------------------------------------

    def queue_anki(self, unit) -> None:
        """Put a word in the queue. Queueing one already there changes
        nothing, not even the date, so the page keeps its order."""
        with open_state(self._db) as conn:
            conn.execute(
                "INSERT INTO anki_words (kind, key, queued)"
                " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (unit.kind, unit.key, datetime.now().isoformat()))

    def unqueue_anki(self, unit) -> None:
        with open_state(self._db) as conn:
            conn.execute("DELETE FROM anki_words WHERE kind = %s AND key = %s",
                         (unit.kind, unit.key))

    def anki_queue(self) -> dict[tuple[str, str], str]:
        """(kind, key) -> when it was queued, newest first."""
        with open_state(self._db) as conn:
            return {(row[0], row[1]): row[2] for row in conn.execute(
                "SELECT kind, key, queued FROM anki_words"
                " ORDER BY queued DESC, key")}

    def note_anki_export(self, units) -> None:
        """Say these words have been written to a file the reader can import.

        Called when the file is actually served, not when it is built, so a
        page that merely renders the queue does not clear the reminder.
        """
        now = datetime.now().isoformat()
        with open_state(self._db) as conn:
            conn.executemany(
                "UPDATE anki_words SET exported = %s"
                " WHERE kind = %s AND key = %s",
                [(now, u.kind, u.key) for u in units])

    def anki_unexported(self) -> int:
        """How many queued words have never been written to a file."""
        with open_state(self._db) as conn:
            return conn.execute(
                "SELECT count(*) FROM anki_words WHERE exported IS NULL"
            ).fetchone()[0]

    # --- how good a sentence is ------------------------------------------

    def mark(self, text: str, verdict: float, source: str = READER) -> None:
        """Record how good a sentence is, 0 to 1, higher better.

        `source` says who thought so — `reader` or `model` — because the two
        deserve different treatment later and neither is worth keeping if it
        cannot be told from the other.
        """
        with open_state(self._db) as conn:
            conn.execute(
                "INSERT INTO sentence_verdict"
                " (text, verdict, source, made_at) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (text, source) DO UPDATE SET"
                " verdict = excluded.verdict, made_at = excluded.made_at",
                (text, max(0.0, min(1.0, verdict)), source,
                 datetime.now().isoformat()))

    def unmark(self, text: str) -> None:
        """Forget the verdict and let the sentence rank on its own merits."""
        with open_state(self._db) as conn:
            conn.execute("DELETE FROM sentence_verdict WHERE text = %s", (text,))

    def mark_many(self, verdicts: dict[str, float], source: str,
                  judged=None) -> None:
        """Record a whole pass's worth of judgements at once.

        One transaction rather than one per sentence: a pass over the corpus
        produces thousands of these, and opening the database for each cost
        more than the judging did.

        Everything this source said before is dropped first, so re-running a
        pass after its rule changed replaces its opinions instead of leaving
        the old ones beside the new. A reader's marks are untouched -- they
        are a different source, and nothing automatic should overwrite them.

        `judged` says which sentences the pass actually read, when it did
        not read them all. Without it a `--limit 100` run dropped every
        one of the 21,479 marks the full run had made and wrote back a
        hundred -- the whole source replaced by a sample of it. Given the
        texts, only their marks are replaced: a judged sentence the rule no
        longer flags loses its old mark, and an unjudged one keeps it.
        """
        now = datetime.now().isoformat()
        with open_state(self._db) as conn:
            if judged is None:
                conn.execute("DELETE FROM sentence_verdict WHERE source = %s",
                             (source,))
            else:
                conn.executemany(
                    "DELETE FROM sentence_verdict WHERE source = %s AND text = %s",
                    [(source, text) for text in judged])
            conn.executemany(
                "INSERT INTO sentence_verdict"
                " (text, verdict, source, made_at) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (text, source) DO UPDATE SET"
                " verdict = excluded.verdict, made_at = excluded.made_at",
                [(text, max(0.0, min(1.0, verdict)), source, now)
                 for text, verdict in verdicts.items()])

    def verdicts(self) -> dict[str, float]:
        """Every sentence anyone has an opinion about, and what it was.

        Sentences nobody has judged are simply absent. Callers treat a
        missing verdict as "no opinion" rather than as a score, so adding
        this changes the order of nothing that has not been marked.

        Several automatic sources may have judged the same sentence, and
        their verdicts multiply: a fragment that is also dialect is worse than
        either alone, and the product says so without any pass having to know
        what the others found.

        A reader outranks all of them, and does not multiply with them. That
        is the whole point of being able to mark a sentence by hand: a person
        who has looked at what the parser called a fragment and decided it is
        fine has settled the question, and a rule that multiplied their 1.0
        into the machine's 0.4 would leave the sentence demoted anyway and
        give them no way to say otherwise.
        """
        automatic: dict[str, float] = {}
        said: dict[str, float] = {}
        with open_state(self._db) as conn:
            for text, verdict, source in conn.execute(
                    "SELECT text, verdict, source FROM sentence_verdict"):
                if source == READER:
                    said[text] = verdict
                else:
                    automatic[text] = max(
                        0.0, automatic.get(text, 1.0) * verdict)
        return {**automatic, **said}

    # --- correcting the units --------------------------------------------

    def set_units(self, text: str, units: dict[Unit, str]) -> None:
        """Replace what a sentence is taken to contain.

        An empty set is meaningful and kept: it says this sentence teaches
        nothing, which is different from having no opinion about it.
        """
        with open_state(self._db) as conn:
            conn.execute("DELETE FROM sentence_units_override WHERE text = %s",
                         (text,))
            conn.executemany(
                "INSERT INTO sentence_units_override (text, kind, key, surface)"
                " VALUES (%s, %s, %s, %s)",
                [(text, u.kind, u.key, surface) for u, surface in units.items()],
            )
            conn.execute(
                "INSERT INTO corrected_sentences (text, corrected)"
                " VALUES (%s, %s) ON CONFLICT (text)"
                " DO UPDATE SET corrected = excluded.corrected",
                (text, datetime.now().isoformat()))

    def clear_units(self, text: str) -> None:
        """Forget the correction and go back to what the analyser said."""
        with open_state(self._db) as conn:
            conn.execute("DELETE FROM sentence_units_override WHERE text = %s",
                         (text,))
            conn.execute("DELETE FROM corrected_sentences WHERE text = %s", (text,))

    def corrected(self) -> dict[str, dict[Unit, str]]:
        """Every correction, as sentence text -> units and their surfaces."""
        with open_state(self._db) as conn:
            corrected = {row[0]: {} for row in
                         conn.execute("SELECT text FROM corrected_sentences")}
            for text, kind, key, surface in conn.execute(
                "SELECT text, kind, key, surface FROM sentence_units_override"
            ):
                corrected.setdefault(text, {})[Unit(kind, key)] = surface or ""
        return corrected

    def counts(self) -> tuple[int, int]:
        with open_state(self._db) as conn:
            hidden = conn.execute(
                "SELECT count(*) FROM hidden_sentences").fetchone()[0]
            fixed = conn.execute(
                "SELECT count(*) FROM corrected_sentences").fetchone()[0]
        return hidden, fixed
