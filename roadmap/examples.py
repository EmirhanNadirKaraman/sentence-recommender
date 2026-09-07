"""Finding example sentences for a unit at review time.

Kept separate from `CorpusIndex` on purpose.  That index is mutated as the
greedy walk advances, so by the time step 12 is reviewed its state has moved
on; this one is read-only and built over the finished corpus, so it can be
queried at any point with whatever the learner knows *now*.
"""
from __future__ import annotations

from collections import defaultdict

from corpus.sentence import Sentence
from vocab.entry import Unit


class ExampleIndex:
    """Every sentence containing a given unit, ranked for usefulness."""

    def __init__(self, sentences: list[Sentence]) -> None:
        self._by_unit: dict[Unit, list[Sentence]] = defaultdict(list)
        for sentence in sentences:
            for unit in sentence.units:
                self._by_unit[unit].append(sentence)

    def count(self, unit: Unit) -> int:
        return len(self._by_unit.get(unit, ()))

    def examples(
        self,
        unit: Unit,
        known: frozenset[Unit],
        limit: int = 3,
    ) -> list[Sentence]:
        """The `limit` most readable sentences using `unit`.

        Ranked by how much else in them is unknown, because an example is only
        useful if the learner can read the rest of it.  A translation breaks
        ties — it makes an otherwise opaque sentence usable — and shorter wins
        after that.
        """
        candidates = self._by_unit.get(unit, ())
        return sorted(
            candidates,
            key=lambda s: (
                len(s.units - known - {unit}),
                s.translation is None,
                len(s.text),
            ),
        )[:limit]
