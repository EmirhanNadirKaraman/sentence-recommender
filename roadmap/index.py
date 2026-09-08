"""The bipartite index the greedy walk runs on.

Nothing is rescanned.  Rebuilding over a quarter of a million sentences after
every step would make the walk quadratic, so the index is built once and
maintained incrementally.  Learning a unit touches only the sentences
containing it, and each of those moves down one state:

  0 unknowns   readable — the goal, counted only
  1 unknown    the frontier; its single unknown is a candidate to teach next
  2 unknowns   the lookahead; learning either one turns the sentence into i+1

Both the candidate map and the lookahead are kept as memberships rather than
recomputed, which is the difference between a walk that takes a minute and one
that takes a moment: at 258k sentences the frontier alone runs to tens of
thousands of sentences, and a set difference per sentence per step dominates
everything else.
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
        self._units = set(known.units)          # mutable mirror, for membership
        self._by_unit: dict[Unit, set[int]] = defaultdict(set)
        for position, sentence in enumerate(sentences):
            for unit in sentence.units:
                self._by_unit[unit].add(position)

        self._unknown = [len(s.units - self._units) for s in sentences]
        self._candidates: dict[Unit, set[int]] = defaultdict(set)
        self._pending: dict[Unit, set[int]] = defaultdict(set)
        self._readable = 0
        for position, count in enumerate(self._unknown):
            if count == 0:
                self._readable += 1
            elif count <= 2:
                self._register(position, count)

    def __len__(self) -> int:
        return len(self._sentences)

    def sentence(self, position: int) -> Sentence:
        return self._sentences[position]

    def unknown_count(self, position: int) -> int:
        return self._unknown[position]

    @property
    def known(self) -> frozenset[Unit]:
        """What this index currently counts as known."""
        return frozenset(self._units)

    def known_units_of_kind(self, kind: str) -> set[Unit]:
        return {u for u in self._by_unit if u.kind == kind}

    @property
    def readable(self) -> int:
        """How many sentences have nothing unknown left in them."""
        return self._readable

    def candidates(self) -> dict[Unit, list[int]]:
        """Every unit that is the *only* unknown in at least one sentence.

        These are exactly the units learnable next: each turns the sentences
        listed against it from i+1 into fully readable.
        """
        return {
            unit: list(positions)
            for unit, positions in self._candidates.items()
            if positions
        }

    def unlocks(self, unit: Unit) -> int:
        """Sentences that would drop from two unknowns to one — the lookahead."""
        return len(self._pending[unit])

    def learn(self, unit: Unit) -> None:
        """Mark `unit` known and move every sentence containing it down a state.

        Learning something already known is a no-op rather than a second
        decrement. Without that guard a caller that forgets to check drives
        unknown counts below zero — silently, since nothing downstream
        inspects the sign — and the frontier stops meaning anything.
        """
        if unit in self._units:
            return
        self._known.learn(unit)
        self._units.add(unit)
        for position in self._by_unit[unit]:
            count = self._unknown[position] - 1
            self._unknown[position] = count
            if count == 0:
                self._candidates[unit].discard(position)
                self._readable += 1
            elif count == 1:
                self._pending[unit].discard(position)
                self._register(position, 1, drop_from_pending=True)
            elif count == 2:
                self._register(position, 2)

    def _register(self, position: int, count: int, drop_from_pending: bool = False) -> None:
        """File a sentence under whichever of its unknowns the walk needs.

        One unknown makes it a candidate for that unit; two put it in both
        units' lookahead.  `drop_from_pending` handles the 2 -> 1 move, where
        the surviving unknown must leave the lookahead as it enters the
        frontier.
        """
        for remaining in self._sentences[position].units - self._units:
            if count == 1:
                if drop_from_pending:
                    self._pending[remaining].discard(position)
                self._candidates[remaining].add(position)
            else:
                self._pending[remaining].add(position)
