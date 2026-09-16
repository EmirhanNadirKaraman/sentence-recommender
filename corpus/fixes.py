"""The model's repair of a sentence, kept beside the original.

Subtitle German arrives with the damage of its medium: a missing full stop, a
lowercase opening where the line was cut, `Ã¼` where an encoding went wrong,
a word the transcriber misheard. `corpus.quality` charges for some of that and
`corpus.llm_corrector` repairs it at build time, but neither can help a
sentence already in the corpus.

Kept beside, never in place, and that is the whole design. Every store in this
project is keyed by sentence text -- the verdicts, the glosses, the vectors,
`roadmap_example` itself -- so rewriting a sentence where it sits would orphan
all of them at once. The original stays the key and the repair is something a
renderer may show instead.

What that costs is honest and small: quality, units and the walk all still see
the original, so a repaired typo does not change what a sentence teaches. What
it buys is that nothing can be lost. A bad fix is one row to delete.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from state import open_state

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentence_fix (
    text    TEXT PRIMARY KEY,
    fixed   TEXT NOT NULL,
    model   TEXT NOT NULL,
    made_at TEXT NOT NULL
);
"""


# Mojibake: what a UTF-8 umlaut looks like read as Latin-1, plus the
# replacement character a lossy decode leaves behind.
BROKEN = re.compile(r"[\ufffd]|Ã[\u00a4\u00b6\u00bc\u009f]|â\u20ac")
TERMINAL = re.compile(r"[.!?]")
LETTERS = re.compile(r"[^\w]", re.UNICODE)


def real_damage(original: str, fixed: str) -> bool:
    """Is this repair fixing something broken, or just restyling?

    The model was asked to correct punctuation, capitalisation and spelling,
    and it does — but it also has opinions. Reading the first 1,460 answers,
    the changes fall into three kinds:

        Du wirst alles sagen Wir möchten…   ->  … sagen. Wir möchten…
            a sentence boundary that was lost. Real.

        Aber du hast gesagt, ja, ich weiß.  ->  … gesagt: Ja, ich weiß.
            a comma to a colon before reported speech. German style allows
            both, nothing was wrong, and it is not this pass's business.

        Was zum % # machst du hier?         ->  Was zum Teufel machst du hier?
            the model guessing at censored text. Not a repair at all: it
            invented a word, and the retention guard let it through because
            everything else stayed.

    So a repair counts when the letters are untouched -- proving no word was
    added, dropped or swapped -- and it either restores a sentence boundary or
    capitalises an opening that was lowercase. Mojibake is the exception that
    may change letters, because repairing it is exactly changing them.
    """
    if BROKEN.search(original):
        return True
    if LETTERS.sub("", original).lower() != LETTERS.sub("", fixed).lower():
        return False                       # a word changed: not punctuation
    if len(TERMINAL.findall(fixed)) > len(TERMINAL.findall(original)):
        return True                        # a lost sentence boundary restored
    head, new_head = original.lstrip()[:1], fixed.lstrip()[:1]
    return head.islower() and new_head.isupper()


class FixStore:
    """Repaired sentences, by the sentence they repair."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def have(self) -> set[str]:
        """Sentences already looked at, so a run can resume.

        Every sentence asked about, not only the ones that needed changing:
        a sentence the model left alone is stored as its own text, because
        "nothing to fix here" is an answer and asking again would cost the
        same as asking the first time.
        """
        with open_state(self._path) as conn:
            return {row[0] for row in conn.execute(
                "SELECT text FROM sentence_fix")}

    def add_many(self, fixes: dict[str, str], model: str) -> None:
        now = datetime.now().isoformat()
        with open_state(self._path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO sentence_fix"
                " (text, fixed, model, made_at) VALUES (?, ?, ?, ?)",
                [(text, fixed, model, now) for text, fixed in fixes.items()])

    def all(self, damaged_only: bool = True) -> dict[str, str]:
        """Repairs worth showing.

        Everything the model changed is stored, because storing it is how a
        rerun knows not to ask again — but only the repairs that fix real
        damage are handed out. `damaged_only=False` returns the rest too, for
        looking at what was rejected and why.
        """
        with open_state(self._path) as conn:
            rows = list(conn.execute("SELECT text, fixed FROM sentence_fix"))
        return {text: fixed for text, fixed in rows
                if fixed != text
                and (not damaged_only or real_damage(text, fixed))}

    def count(self) -> tuple[int, int]:
        """How many were asked about, and how many were changed."""
        with open_state(self._path) as conn:
            asked = conn.execute(
                "SELECT COUNT(*) FROM sentence_fix").fetchone()[0]
            changed = conn.execute(
                "SELECT COUNT(*) FROM sentence_fix"
                " WHERE fixed <> text").fetchone()[0]
        return asked, changed
