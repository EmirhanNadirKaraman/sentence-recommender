"""How urgent a unit is, independent of how much it unlocks.

Both kinds are ranked by one authored list, in the order it was written.
`data/final_result.txt` is frequency-ordered — `haben` first, `sein` second,
`westdeutsch` last — and it names words and verb patterns side by side, so a
single position serves both.

That shared ordering is the point. Words and patterns compete for the same
roadmap slots, and scoring them by unrelated measures — a frequency rank
against a corpus trigger count — meant the comparison was arbitrary. Now a
pattern outranks a word exactly when the list says it is more useful.

A unit absent from the list scores 0: it is not something you set out to
learn, so it wins a slot only on how much it unlocks.
"""
from __future__ import annotations

from typing import Iterable

from vocab.entry import Unit


class UnitPriority:
    """Maps a unit to a teaching priority in [0, 1]; higher is more urgent."""

    def __init__(self, ranks: dict[Unit, int]) -> None:
        self._ranks = ranks
        self._size = max(len(ranks), 1)

    @classmethod
    def build(cls, units: Iterable[Unit]) -> "UnitPriority":
        """Rank units by where they first appear in the list.

        First appearance, because a lemma recurs under several blueprints —
        `verdienen` shows up as both `etw. (Akk) verdienen` and plain
        `verdienen` — and the earliest mention is the one that reflects how
        common it is.
        """
        ranks: dict[Unit, int] = {}
        for position, unit in enumerate(units):
            ranks.setdefault(unit, position)
        return cls(ranks)

    def of(self, unit: Unit) -> float:
        rank = self._ranks.get(unit)
        return 0.0 if rank is None else 1.0 - rank / self._size

    def __len__(self) -> int:
        return len(self._ranks)
