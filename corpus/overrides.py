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

import sqlite3

from state import open_state
from datetime import datetime
from pathlib import Path

from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS hidden_sentences (
    text     TEXT PRIMARY KEY,
    hidden   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sentence_units_override (
    text     TEXT NOT NULL,
    kind     TEXT NOT NULL,
    key      TEXT NOT NULL,
    surface  TEXT,
    PRIMARY KEY (text, kind, key)
);
CREATE TABLE IF NOT EXISTS corrected_sentences (
    text      TEXT PRIMARY KEY,
    corrected TEXT NOT NULL
);
-- 0 to 1, higher is better. Absent means no opinion, which is not the same
-- as a middling one: a sentence nobody has judged should rank on its own
-- merits rather than be penalised for going unread.
CREATE TABLE IF NOT EXISTS sentence_verdict (
    text     TEXT NOT NULL,
    verdict  REAL NOT NULL,
    source   TEXT NOT NULL,
    made_at  TEXT NOT NULL,
    PRIMARY KEY (text, source)
);
"""


# Who said so. A reader is a person looking at the sentence; everything else
# is a pass that judged it without one.
READER = "reader"


class SentenceOverrides:
    """What the reader has said about particular sentences."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)
            self._widen_verdict_key(conn)

    @staticmethod
    def _widen_verdict_key(conn) -> None:
        """Let one sentence carry a verdict from each source that judged it.

        The table began keyed on the text alone, which was right while a
        reader was the only one marking anything. It stopped being right the
        moment two automatic passes existed: the parser marks a sentence for
        having no verb, a second pass marks it for being dialect, and under
        the old key the second silently replaced the first.

        `CREATE TABLE IF NOT EXISTS` cannot widen a key, so this is the
        create-copy-swap SQLite requires, guarded on the stored definition so
        it runs once. The rows are kept: they are judgements someone paid for.
        """
        columns = list(conn.execute("PRAGMA table_info(sentence_verdict)"))
        if not columns:
            return
        keyed = [row[1] for row in columns if row[5]]      # row[5] is pk order
        if keyed == ["text", "source"]:
            return
        conn.executescript("""
            CREATE TABLE sentence_verdict_wide (
                text     TEXT NOT NULL,
                verdict  REAL NOT NULL,
                source   TEXT NOT NULL,
                made_at  TEXT NOT NULL,
                PRIMARY KEY (text, source)
            );
            INSERT OR REPLACE INTO sentence_verdict_wide
                 (text, verdict, source, made_at)
            SELECT text, verdict, source, made_at FROM sentence_verdict;
            DROP TABLE sentence_verdict;
            ALTER TABLE sentence_verdict_wide RENAME TO sentence_verdict;
        """)

    # --- hiding ----------------------------------------------------------

    def hide(self, text: str) -> None:
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO hidden_sentences (text, hidden)"
                " VALUES (?, ?)", (text, datetime.now().isoformat()))

    def show(self, text: str) -> None:
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM hidden_sentences WHERE text = ?", (text,))

    def hidden(self) -> set[str]:
        with open_state(self._path) as conn:
            return {row[0] for row in
                    conn.execute("SELECT text FROM hidden_sentences")}

    # --- how good a sentence is ------------------------------------------

    def mark(self, text: str, verdict: float, source: str = READER) -> None:
        """Record how good a sentence is, 0 to 1, higher better.

        `source` says who thought so — `reader` or `model` — because the two
        deserve different treatment later and neither is worth keeping if it
        cannot be told from the other.
        """
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sentence_verdict"
                " (text, verdict, source, made_at) VALUES (?, ?, ?, ?)",
                (text, max(0.0, min(1.0, verdict)), source,
                 datetime.now().isoformat()))

    def unmark(self, text: str) -> None:
        """Forget the verdict and let the sentence rank on its own merits."""
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM sentence_verdict WHERE text = ?", (text,))

    def mark_many(self, verdicts: dict[str, float], source: str) -> None:
        """Record a whole pass's worth of judgements at once.

        One transaction rather than one per sentence: a pass over the corpus
        produces thousands of these, and opening the database for each cost
        more than the judging did.

        Everything this source said before is dropped first, so re-running a
        pass after its rule changed replaces its opinions instead of leaving
        the old ones beside the new. A reader's marks are untouched -- they
        are a different source, and nothing automatic should overwrite them.
        """
        now = datetime.now().isoformat()
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM sentence_verdict WHERE source = ?",
                         (source,))
            conn.executemany(
                "INSERT OR REPLACE INTO sentence_verdict"
                " (text, verdict, source, made_at) VALUES (?, ?, ?, ?)",
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
        with open_state(self._path) as conn:
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
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM sentence_units_override WHERE text = ?",
                         (text,))
            conn.executemany(
                "INSERT INTO sentence_units_override (text, kind, key, surface)"
                " VALUES (?, ?, ?, ?)",
                [(text, u.kind, u.key, surface) for u, surface in units.items()],
            )
            conn.execute(
                "INSERT OR REPLACE INTO corrected_sentences (text, corrected)"
                " VALUES (?, ?)", (text, datetime.now().isoformat()))

    def clear_units(self, text: str) -> None:
        """Forget the correction and go back to what the analyser said."""
        with open_state(self._path) as conn:
            conn.execute("DELETE FROM sentence_units_override WHERE text = ?",
                         (text,))
            conn.execute("DELETE FROM corrected_sentences WHERE text = ?", (text,))

    def corrected(self) -> dict[str, dict[Unit, str]]:
        """Every correction, as sentence text -> units and their surfaces."""
        with open_state(self._path) as conn:
            corrected = {row[0]: {} for row in
                         conn.execute("SELECT text FROM corrected_sentences")}
            for text, kind, key, surface in conn.execute(
                "SELECT text, kind, key, surface FROM sentence_units_override"
            ):
                corrected.setdefault(text, {})[Unit(kind, key)] = surface or ""
        return corrected

    def counts(self) -> tuple[int, int]:
        with open_state(self._path) as conn:
            hidden = conn.execute(
                "SELECT count(*) FROM hidden_sentences").fetchone()[0]
            fixed = conn.execute(
                "SELECT count(*) FROM corrected_sentences").fetchone()[0]
        return hidden, fixed
