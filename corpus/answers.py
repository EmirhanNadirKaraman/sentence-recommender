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

from corpus.questions import LEVELS
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
# Below this, `plain` is a no: the sentence does not say the word. Read
# from the answers on 2026-09-21 — under .1 is all look-alikes (`gehört`
# as `gehören`, `magst` as `der Magen`, `gelassen` as `lassen`), .1–.2 is
# the same with `pass auf` as `der Pass` and `das Sagen` as `sagen`, and
# from .2 up the fixed expressions begin to mix with the word itself
# (`100 Jahre` at .19 is the one false no seen in the band). 403 pairs.
DOUBT = 0.2
# What a level costs an example, as a share: an A1 sentence is worth all of
# its quality, a B1 one three fifths, a B2 one two fifths. Measured on the
# beginner plan's stored candidates before it was chosen (TODO #27): a
# level used only to break ties moved nothing, because the judge's product
# is a continuous number and ties are rare; at .1 a level the plan's B1
# sentences fell from 1,644 to 1,462, at .2 to 1,178, at .3 to 966, giving
# up .02, .03 and .07 of the product on the picks that changed.
LEVEL_COST = 0.2


class Judged:
    """The answers of one model at one version, ready to rank with.

    Absent means unjudged, and unjudged scores as a *typical* judged
    sentence — the median of what the judge has said — not as a perfect
    one. `verdicts` can default to 1.0 because a reader marks only what is
    bad; the judge answers for everything it is asked, so a sentence with
    no answer is one nobody has asked about yet. The walk picks a card's
    candidates with this key from every sentence that says the word, and
    the pass judges only the candidates it finds stored: at 1.0 the
    unjudged thousands would win every pick and the answers would order
    nothing. At the median, a sentence the judge called good stays in, one
    it called bad drops out, and what replaces it is judged next run. With
    nothing judged at all the median is 1.0, and nothing moves.
    """

    def __init__(self, quality: dict[str, float],
                 fit: dict[str, dict[tuple[str, str], float]],
                 typical_quality: float = 1.0, typical_fit: float = 1.0,
                 levels: dict[str, float] | None = None,
                 typical_level: float = 0.0) -> None:
        self._quality = quality
        self._fit = fit
        self._typical_quality = typical_quality
        self._typical_fit = typical_fit
        self._levels = levels or {}
        self._typical_level = typical_level
        # Once, here: `apply_overrides` asks for it on every load and on
        # every stored deck it hands out, a roadmap page's worth at a time.
        self._doubted = {text: frozenset(key for (_, key), value in found.items()
                                         if value < DOUBT)
                         for text, found in fit.items()
                         if any(value < DOUBT for value in found.values())}

    def sentence(self, text: str) -> float:
        """How much the judge thinks the sentence is worth showing at all:
        the four quality answers multiplied, each a probability."""
        return self._quality.get(text, self._typical_quality)

    def worth(self, text: str, unit: Unit) -> float:
        """What the judge makes of the sentence as an example of `unit`,
        all in: worth showing at all, the word itself, and its level. The
        one product every ranking multiplies in -- the walk, the deck, the
        teaching sentence, the quiz -- so that no two of them can weigh
        the same sentence differently."""
        return self.sentence(text) * self.unit(text, unit) * self.ease(text)

    def unit(self, text: str, unit: Unit) -> float:
        """How well the sentence serves as an example of `unit`: `plain` —
        the word itself, not a fixed expression or a look-alike. A refused
        gloss is a pair the model would not read as the word, and counts
        as `plain` 0.

        `guessable` is stored where it was asked and read nowhere. It
        ranked weakly in its calibration and was the first question left
        out to meet a budget, and a factor that only some sentences carry
        would order the judged below the unjudged.
        """
        found = self._fit.get(text)
        if not found:
            return self._typical_fit
        return found.get((unit.kind, unit.key), self._typical_fit)

    def level(self, text: str) -> str | None:
        """The level the judge gave the sentence, as its nearest label —
        `B1` — or None where it was never asked."""
        found = self._levels.get(text)
        if found is None:
            return None
        return label(found)

    def expected(self, text: str) -> float | None:
        """The level as the judge's expectation, in levels above A1 (0–4),
        or None where it was never asked; what a video's mean is made of."""
        return self._levels.get(text)

    def ease(self, text: str) -> float:
        """How much of a sentence's worth its level leaves it, for a reader
        starting from nothing: `1 - LEVEL_COST` a level above A1.

        Lower is better, unconditionally. The plans are walked for a
        reader who begins at the beginning, and every word is taught from
        the sentences that say it, so among sentences the judge thinks
        equally good the one a beginner could read wins. A reader's own
        level is the obvious parameter here and is not one yet; nobody has
        asked for harder. Unjudged scores as the median judged level, for
        the reason given above for quality: at A1 it would win every pick.
        With nothing judged at all the median is A1 and nothing moves.
        """
        level = self._levels.get(text, self._typical_level)
        return max(0.0, 1.0 - LEVEL_COST * level)

    def doubted(self) -> dict[str, frozenset[str]]:
        """Per sentence, the pattern keys the judge says it does not say.

        A `plain` under `DOUBT`, or a gloss refused: the matcher found the
        word's letters and the sentence has another word in them — `gehört`
        is `hören`, not `gehören`. Applied where the corpus is read, so the
        pair is not merely ranked last for the word's own card but stops
        counting as an occurrence anywhere: the walk's gain, the reel's
        "one word away", `/blocked`, comprehension.
        """
        return self._doubted

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

    def answered(self, model: str, version: int,
                 questions: tuple[str, ...] = ("complete",)) -> set[str]:
        """The sentences this model has answered at this version — what a
        resumed pass skips: those holding every one of `questions`. A pass
        that asks `level` alone of a video's lines skips what the full
        pass already levelled, and the full pass, asking `complete` among
        the rest, does not skip a sentence that has only the level."""
        marks = ", ".join("?" for _ in questions)
        with open_state(self._path) as conn:
            return {text for (text,) in conn.execute(
                "SELECT text FROM sentence_answer"
                f" WHERE question IN ({marks}) AND version = ? AND model = ?"
                " GROUP BY text HAVING count(DISTINCT question) = ?",
                (*questions, version, model, len(questions)))}

    def counts(self) -> dict[str, int]:
        with open_state(self._path) as conn:
            return {q: n for q, n in conn.execute(
                "SELECT question, count(*) FROM sentence_answer GROUP BY question")}

    def load(self, model: str, version: int) -> Judged:
        """The answers as something `rank` can read, in memory.

        A few million rows for the whole build, read once per process: the
        quality product per sentence, the level, and per sentence the fit
        of each unit the judge was asked about. Refusals count regardless
        of version and model — they were never versioned questions, and
        the model that refused is the gloss's, not the judge's; read by
        the judge's name they were never read at all.
        """
        quality: dict[str, float] = {}
        levels: dict[str, float] = {}
        plain: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)
        with open_state(self._path) as conn:
            for text, kind, key, question, value in conn.execute(
                    "SELECT text, kind, key, question, value FROM sentence_answer"
                    " WHERE (model = ? AND version = ?) OR question = ?",
                    (model, version, REFUSED)):
                if question in QUALITY:
                    quality[text] = quality.get(text, 1.0) * value
                elif question == "level":
                    # Stored scaled to 0–1 over the labels; read as levels
                    # above A1, which is what `ease` charges for.
                    levels[text] = value * (len(LEVELS) - 1)
                elif question == "plain":
                    plain[text][(kind, key)] = value
                elif question == REFUSED:
                    plain[text][(kind, key)] = 0.0
        return Judged(quality, dict(plain),
                      _median(quality.values()),
                      _median(v for units in plain.values() for v in units.values()
                              if v > 0.0),          # refusals are not answers
                      levels, _median(levels.values()) if levels else 0.0)


def label(level: float) -> str:
    """The nearest of A1–C1 to a level counted above A1."""
    return LEVELS[min(range(len(LEVELS)), key=lambda i: abs(i - level))]


def _median(values) -> float:
    """The middle of what the judge said, or 1.0 when it said nothing."""
    found = sorted(values)
    return found[len(found) // 2] if found else 1.0
