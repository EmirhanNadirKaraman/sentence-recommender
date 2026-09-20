"""Turning a due card into what the terminal actually shows.

Every card carries several examples, not one.  A single sentence teaches a
word in one grammatical shape; a handful shows the range, and where a
translation exists it goes underneath so the sentence stays readable even
when the rest of it is not yet fully known.

  word     cloze — the examples with the word blanked out.  The learner types
           the missing word, which is checked automatically.
  pattern  the frame itself ("jdm. (Dat) etw. (Akk) geben").  The learner
           writes their own sentence and grades it against the examples,
           because nothing here can judge free production.
"""
from __future__ import annotations

from dataclasses import dataclass

from corpus.sentence import Sentence
from srs.card import Card
from vocab.entry import Unit

BLANK = "_____"


@dataclass(frozen=True)
class ReviewPrompt:
    """What to show, what counts as right, and how it is graded."""

    card: Card
    heading: str
    examples: tuple[Sentence, ...]
    cloze: tuple[str, ...]
    answer: str
    self_graded: bool

    @property
    def unit(self) -> Unit:
        return self.card.unit

    def question_lines(self) -> list[str]:
        """What the learner sees before answering."""
        if not self.examples:
            return ["   (no example sentences available)"]
        if self.cloze:
            lines = []
            for blanked, example in zip(self.cloze, self.examples):
                lines.append(f"   {blanked}")
                if example.translation:
                    lines.append(f"      {example.translation}")
            return lines
        # Pattern cards withhold the German entirely — the translations say
        # what to express, and the sentences are the answer.
        return [f"   • {e.translation or e.text}" for e in self.examples]

    def answer_lines(self) -> list[str]:
        """What is revealed once they have answered."""
        return [f"   {e.text}" for e in self.examples]


class PromptBuilder:
    def __init__(self, examples, count: int = 3, translate=None,
                 verdicts=None, judged=None) -> None:
        """`translate` maps sentences to the same sentences carrying whatever
        English exists for them -- `Application.with_english`. Without it a
        card shows only what the corpus shipped.

        `verdicts` and `judged` are what a reader and the corpus pass's
        judge have said about sentences, passed as every other ranking
        passes them; left out, a review card ranked its examples by
        characters alone and could show a sentence the judge had marked
        glued or garbled."""
        self._examples = examples
        self._count = count
        self._translate = translate
        self._verdicts = verdicts
        self._judged = judged

    def build(self, card: Card, known: frozenset[Unit]) -> ReviewPrompt:
        found = tuple(self._examples.examples(card.unit, known, self._count,
                                              verdicts=self._verdicts,
                                              judged=self._judged))
        if self._translate is not None:
            found = tuple(self._translate(found))
        if card.unit.is_pattern:
            return ReviewPrompt(
                card=card,
                heading=f"Write a sentence using:  {card.unit.key}",
                examples=found,
                cloze=(),
                answer=card.unit.key,
                self_graded=True,
            )
        return ReviewPrompt(
            card=card,
            heading="Which word fills the blanks?",
            examples=found,
            cloze=tuple(self._blank(s, card.unit) for s in found),
            answer=card.unit.key,
            self_graded=False,
        )

    @staticmethod
    def _blank(sentence: Sentence, unit: Unit) -> str:
        """The sentence with `unit`'s surface form replaced.

        Falls back to the untouched sentence when the surface was not recorded
        — a visible example beats no example, even if it gives the answer away.
        """
        surface = sentence.surface_of(unit)
        if not surface or surface not in sentence.text:
            return sentence.text
        return sentence.text.replace(surface, BLANK)
