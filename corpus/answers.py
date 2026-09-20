"""What a judge answered about a sentence, or about a word in it.

The corpus pass (`ask-sentences`) asks every question in `corpus.questions`
of every teachable subtitle sentence, once, and the answers land here raw:
a probability for a Noul, an expected level for a Score, a label and its
distribution for a Choice. No threshold is stored. The policy that reads
them — what counts as a good example, what is worth showing — lives in
code, so a change of policy is a `WHERE`, not a rerun.

Keyed on the sentence text, the unit the question was about (blank for a
question about the sentence itself), the question, its version and the
model. Two models answering one question, or one model answering two
wordings, are different rows; nothing here is compared across them. The
version is `questions.VERSION` at the time of asking.

The gloss's refusal lives here too, under `gloss_refused`, keyed on the
pair. It used to be a `sentence_verdict` on the text alone, which kept a
perfectly good `es gibt` sentence off every card because the model would
not gloss it as `geben`; the refusal was about the pair all along.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from state import open_state
from vocab.entry import Unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentence_answer (
    text         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT '',
    key          TEXT NOT NULL DEFAULT '',
    question     TEXT NOT NULL,
    version      INTEGER NOT NULL,
    model        TEXT NOT NULL,
    value        REAL NOT NULL,
    distribution TEXT,
    made_at      TEXT NOT NULL,
    PRIMARY KEY (text, kind, key, question, version, model)
);
CREATE INDEX IF NOT EXISTS ix_sentence_answer_question
    ON sentence_answer (question, version, model);
"""

# The questions about the sentence itself, whose product is its quality.
QUALITY = ("stands_alone", "complete", "standard", "well_formed")
REFUSED = "gloss_refused"


class Judged:
    """The answers of one model at one version, ready to rank with.

    Absent means unjudged and scores 1.0 — the best — so a store with no
    rows reorders nothing, exactly as `verdicts` behaves. Only a sentence
    the judge has actually doubted moves, and it moves down.
    """

    def __init__(self, quality: dict[str, float],
                 fit: dict[str, dict[tuple[str, str], float]]) -> None:
        self._quality = quality
        self._fit = fit

    def sentence(self, text: str) -> float:
        """How much the judge thinks the sentence is worth showing at all:
        the four quality answers multiplied, each a probability."""
        return self._quality.get(text, 1.0)

    def unit(self, text: str, unit: Unit) -> float:
        """How well the sentence serves as an example of `unit`.

        `plain` first — the word itself, not a fixed expression or a
        look-alike — scaled by how much the sentence gives the word away,
        which ranks but never gates: a sentence the judge is sure is the
        word keeps at least half its worth however little it explains. A
        refused gloss is a pair the model would not read as the word, and
        counts as `plain` 0.
        """
        found = self._fit.get(text)
        if not found:
            return 1.0
        return found.get((unit.kind, unit.key), 1.0)

    def __len__(self) -> int:
        return len(self._quality)


class AnswerStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)

    def save(self, text: str, model: str, version: int,
             answers: dict[str, tuple[float, dict | None]],
             units: dict[str, Unit] | None = None) -> None:
        """Every answer for one sentence, in one transaction.

        `answers` maps a question id to `(value, distribution)`. A per-unit
        id is written `plain:u1`; `units` says which unit `u1` was.
        """
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for ident, (value, distribution) in answers.items():
            question, _, unit_id = ident.partition(":")
            unit = units[unit_id] if unit_id and units else None
            rows.append((text, unit.kind if unit else "", unit.key if unit else "",
                         question, version, model, float(value),
                         json.dumps(distribution, ensure_ascii=False) if distribution else None,
                         now))
        with open_state(self._path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO sentence_answer"
                " (text, kind, key, question, version, model, value, distribution, made_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def refuse(self, text: str, unit: Unit, model: str) -> None:
        """The gloss would not read this sentence as this word."""
        with open_state(self._path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sentence_answer"
                " (text, kind, key, question, version, model, value, distribution, made_at)"
                " VALUES (?, ?, ?, ?, 0, ?, 1.0, NULL, ?)",
                (text, unit.kind, unit.key, REFUSED, model,
                 datetime.now().isoformat(timespec="seconds")))

    def answered(self, model: str, version: int) -> set[str]:
        """The sentences this model has answered at this version — what a
        resumed pass skips."""
        with open_state(self._path) as conn:
            return {text for (text,) in conn.execute(
                "SELECT DISTINCT text FROM sentence_answer"
                " WHERE question = 'complete' AND version = ? AND model = ?",
                (version, model))}

    def counts(self) -> dict[str, int]:
        with open_state(self._path) as conn:
            return {q: n for q, n in conn.execute(
                "SELECT question, count(*) FROM sentence_answer GROUP BY question")}

    def load(self, model: str, version: int) -> Judged:
        """The answers as something `rank` can read, in memory.

        A few million rows for the whole build, read once per process: the
        quality product per sentence, and per sentence the fit of each unit
        the judge was asked about. Refusals count regardless of version —
        they were never versioned questions.
        """
        quality: dict[str, float] = {}
        plain: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)
        guess: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)
        with open_state(self._path) as conn:
            for text, kind, key, question, value in conn.execute(
                    "SELECT text, kind, key, question, value FROM sentence_answer"
                    " WHERE model = ? AND (version = ? OR question = ?)",
                    (model, version, REFUSED)):
                if question in QUALITY:
                    quality[text] = quality.get(text, 1.0) * value
                elif question == "plain":
                    plain[text][(kind, key)] = value
                elif question == "guessable":
                    guess[text][(kind, key)] = value
                elif question == REFUSED:
                    plain[text][(kind, key)] = 0.0
        fit: dict[str, dict[tuple[str, str], float]] = {}
        for text, units in plain.items():
            fit[text] = {unit: p * (0.5 + 0.5 * guess.get(text, {}).get(unit, 1.0))
                         for unit, p in units.items()}
        return Judged(quality, fit)
