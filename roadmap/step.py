"""One entry in the roadmap."""
from __future__ import annotations

from dataclasses import dataclass

from corpus.sentence import Sentence
from vocab.entry import Unit


@dataclass(frozen=True)
class RoadmapStep:
    """A single unit to learn, with the sentence that teaches it.

    `sentence` is i+1 at this point in the sequence: every unit in it except
    `unit` is already known.  `gain` is how many sentences the step moves
    forward — those it makes fully readable plus those it brings down to a
    single unknown.

    `examples` is the deck the reader steps through, chosen during the walk
    against what they know by the time they reach this step.  It is stored
    with the step so the page can be served without the corpus in memory;
    `readable` and `occurrences` are there for the same reason — the two
    counts the page states, which otherwise take a corpus-wide index to
    answer.
    """

    position: int
    unit: Unit
    sentence: Sentence
    gain: int
    score: float
    now_readable: int
    examples: tuple[Sentence, ...] = ()
    readable: int = 0
    occurrences: int = 0

    def describe(self) -> str:
        kind = "pattern" if self.unit.is_pattern else "word"
        return f"{self.position:>4}. [{kind:>7}] {self.unit.key}"
