"""The atom of the whole system: a single thing that can be known or not known."""
from __future__ import annotations

from dataclasses import dataclass, field

LEMMA = "lemma"
PATTERN = "pattern"


@dataclass(frozen=True, slots=True)
class Unit:
    """A learning unit.

    Two kinds share one type because the roadmap treats them identically —
    a sentence is i+1 when it contains exactly one unknown *unit*, whichever
    kind that is.

    kind == LEMMA    key is a lowercase lemma from `word_table.lemma`
    kind == PATTERN  key is a `phrase_table.canonical`, e.g.
                     "jdm. (Dat) etw. (Akk) geben"
    """

    kind: str
    key: str
    _hash: int = field(default=0, init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_hash", hash((self.kind, self.key)))

    def __hash__(self) -> int:
        """The hash, computed once when the unit is made.

        The walk looks every candidate up in the lookahead, the priority
        ranking and the goal set on every step, which came to a hundred and
        fifty million hashes over three thousand steps — and the generated
        one builds a tuple each time.  This makes it an attribute read.
        """
        return self._hash

    @classmethod
    def lemma(cls, key: str) -> "Unit":
        return cls(LEMMA, key.lower())

    @classmethod
    def pattern(cls, key: str) -> "Unit":
        return cls(PATTERN, key)

    @property
    def is_pattern(self) -> bool:
        return self.kind == PATTERN

    def __str__(self) -> str:
        return f"{self.kind}:{self.key}"
