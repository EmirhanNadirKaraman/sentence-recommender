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
    """

    position: int
    unit: Unit
    sentence: Sentence
    gain: int
    score: float
    now_readable: int

    def describe(self) -> str:
        kind = "pattern" if self.unit.is_pattern else "word"
        return f"{self.position:>4}. [{kind:>7}] {self.unit.key}"
