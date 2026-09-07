"""The atom of the whole system: a single thing that can be known or not known."""
from __future__ import annotations

from dataclasses import dataclass

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
