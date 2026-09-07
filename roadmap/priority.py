"""How urgent a unit is, independent of how much it unlocks.

Both unit kinds are scored onto the same [0, 1] scale, because they compete
for the same roadmap slots.  Leaving patterns unscored would hand every word
a permanent head start and quietly produce a word-only roadmap.

  lemma   — position in the top-4000 frequency list; unlisted words score 0
  pattern — how many corpus sentences trigger it, relative to the most
            widely triggered pattern
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from corpus.sentence import Sentence
from vocab.entry import Unit


class UnitPriority:
    """Maps a unit to a teaching priority in [0, 1]; higher is more urgent."""

    def __init__(self, lemma_ranks: dict[str, int], pattern_counts: Counter[str]) -> None:
        self._ranks = lemma_ranks
        self._size = max(len(lemma_ranks), 1)
        self._counts = pattern_counts
        self._max_count = max(pattern_counts.values(), default=1)

    @classmethod
    def build(cls, priority_lemmas: list[str], sentences: Iterable[Sentence]) -> "UnitPriority":
        counts: Counter[str] = Counter()
        for sentence in sentences:
            for unit in sentence.units:
                if unit.is_pattern:
                    counts[unit.key] += 1
        return cls({lemma: i for i, lemma in enumerate(priority_lemmas)}, counts)

    def of(self, unit: Unit) -> float:
        if unit.is_pattern:
            return self._counts.get(unit.key, 0) / self._max_count
        rank = self._ranks.get(unit.key)
        return 0.0 if rank is None else 1.0 - rank / self._size
