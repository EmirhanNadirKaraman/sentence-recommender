"""What the learner already knows, and how it grows as the roadmap advances."""
from __future__ import annotations

from typing import Iterable, Iterator

from vocab.entry import Unit


class KnownSet:
    """A mutable set of units.

    It starts as the vocabulary files resolved into corpus lemmas, and the
    roadmap builder adds one unit to it per step — each step is defined
    relative to everything learned before it, which is what makes the output a
    sequence rather than a filtered list.
    """

    def __init__(self, units: Iterable[Unit] = ()) -> None:
        self._units: set[Unit] = set(units)
        self._seeded = frozenset(self._units)

    def __contains__(self, unit: object) -> bool:
        return unit in self._units

    def __len__(self) -> int:
        return len(self._units)

    def __iter__(self) -> Iterator[Unit]:
        return iter(self._units)

    @property
    def units(self) -> frozenset[Unit]:
        return frozenset(self._units)

    @property
    def learned(self) -> frozenset[Unit]:
        """Everything added since the starting set — i.e. the roadmap so far."""
        return frozenset(self._units) - self._seeded

    def learn(self, unit: Unit) -> None:
        self._units.add(unit)
