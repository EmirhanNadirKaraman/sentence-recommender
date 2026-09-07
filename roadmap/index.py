"""The bipartite index the greedy walk runs on.

Recomputing every sentence's unknown count after each step would be quadratic.
Instead the index is built once and maintained incrementally: learning a unit
touches only the sentences that contain it, found through the inverted index.
"""
from __future__ import annotations

from collections import defaultdict

from corpus.sentence import Sentence
from roadmap.known_set import KnownSet
from vocab.entry import Unit


class CorpusIndex:
    """Sentences, their unknown counts, and which sentences each unit appears in."""

    def __init__(self, sentences: list[Sentence], known: KnownSet) -> None:
        self._sentences = sentences
        self._known = known
        self._by_unit: dict[Unit, set[int]] = defaultdict(set)
        for position, sentence in enumerate(sentences):
            for unit in sentence.units:
                self._by_unit[unit].add(position)
        self._unknown = [len(sentence.units - known.units) for sentence in sentences]

    def __len__(self) -> int:
        return len(self._sentences)

    def sentence(self, position: int) -> Sentence:
        return self._sentences[position]

    def unknown_count(self, position: int) -> int:
        return self._unknown[position]

    def readable(self) -> list[int]:
        """Sentences with nothing unknown left in them."""
        return [i for i, n in enumerate(self._unknown) if n == 0]

    def candidates(self) -> dict[Unit, list[int]]:
        """Every unit that is the *only* unknown in at least one sentence.

        These are exactly the units learnable next: each one turns the
        sentences listed against it from i+1 into fully readable.
        """
        out: dict[Unit, list[int]] = defaultdict(list)
        known = self._known.units
        for position, count in enumerate(self._unknown):
            if count != 1:
                continue
            unknown = self._sentences[position].units - known
            out[next(iter(unknown))].append(position)
        return out

    def unlocks(self, unit: Unit) -> int:
        """Sentences that would drop from two unknowns to one — the lookahead."""
        return sum(1 for i in self._by_unit[unit] if self._unknown[i] == 2)

    def learn(self, unit: Unit) -> None:
        self._known.learn(unit)
        for position in self._by_unit[unit]:
            self._unknown[position] -= 1
