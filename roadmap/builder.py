"""The greedy i+1 walk.

At every step the builder looks at the units that are the single unknown in
some sentence, and picks the one worth teaching next:

    score = gain + priority_weight * priority

`gain` counts sentences the step moves forward — those it makes fully readable
now, plus those it brings down to one unknown (the lookahead).  `priority`
comes from UnitPriority and breaks the many ties: corpus gains are small, so
without it the walk would wander into rare vocabulary that happens to unlock
one more sentence.
"""
from __future__ import annotations

from corpus.sentence import Sentence
from roadmap.index import CorpusIndex
from roadmap.priority import UnitPriority
from roadmap.step import RoadmapStep
from vocab.entry import Unit


class RoadmapBuilder:
    def __init__(
        self,
        index: CorpusIndex,
        priority: UnitPriority,
        priority_weight: float = 3.0,
    ) -> None:
        self._index = index
        self._priority = priority
        self._weight = priority_weight

    def build(self, max_steps: int | None = None) -> list[RoadmapStep]:
        steps: list[RoadmapStep] = []
        while max_steps is None or len(steps) < max_steps:
            step = self._next_step(len(steps) + 1)
            if step is None:
                break
            steps.append(step)
            self._index.learn(step.unit)
        return steps

    def _next_step(self, position: int) -> RoadmapStep | None:
        candidates = self._index.candidates()
        if not candidates:
            return None
        unit, sentences, gain, score = max(
            (
                (unit, positions, *self._score(unit, positions))
                for unit, positions in candidates.items()
            ),
            key=lambda row: (row[3], row[0].key),   # key breaks ties reproducibly
        )
        return RoadmapStep(
            position=position,
            unit=unit,
            sentence=self._example(sentences),
            gain=gain,
            score=score,
            now_readable=len(sentences),
        )

    def _score(self, unit: Unit, positions: list[int]) -> tuple[int, float]:
        gain = len(positions) + self._index.unlocks(unit)
        return gain, gain + self._weight * self._priority.of(unit)

    def _example(self, positions: list[int]) -> Sentence:
        """The simplest sentence teaching this unit — fewest units wins."""
        return min(
            (self._index.sentence(p) for p in positions),
            key=lambda s: (len(s.units), len(s.text)),
        )
