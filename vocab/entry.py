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

    kind == LEMMA    key is a lemma, lowercase — except the handful of nouns
                     that share one with a verb, which keep their capital to
                     say which of the two they are (`Treffen` the meeting
                     against `treffen` the verb). See `Unit.exact`.
    kind == PATTERN  key is a `phrase_table.canonical`, e.g.
                     "jdm. (Dat) etw. (Akk) geben"
    """

    kind: str
    key: str
    _hash: int = field(default=0, init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_hash", hash((self.kind, self.key)))

    def __reduce__(self):
        """Rebuilt, not restored, on the far side of a pickle.

        The hash above is a per-process number — Python salts string
        hashing at start-up — so a unit handed back from a worker with its
        hash attached lands in the wrong bucket of every set in the parent,
        equal to nothing. `corpus.parallel` found this: two sentences in
        twelve thousand agreed with the single-process answer.
        """
        return (Unit, (self.kind, self.key))

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
        """A lemma unit, lowercased.

        The default, because almost every caller has a written word rather
        than a parse — a study-list entry, a query string, a line of a
        vocabulary file — and none of those can be trusted to carry the case
        the corpus uses. Use `exact` where the parser is the authority.
        """
        return cls(LEMMA, key.lower())

    @classmethod
    def exact(cls, key: str) -> "Unit":
        """A lemma unit with the case it was given.

        Only for lemmas that come from the analyser, which is the one place
        that knows whether a word was a noun or a verb. German makes a noun of
        an infinitive — das Treffen against treffen — and spaCy keeps them
        apart by exactly that capital. `lemma` would throw it away, which is
        what it did: the analyser was taught to preserve the noun and the very
        next line lowercased it again, so a fourteen-minute rebuild changed
        nothing at all. See the analyser's `noun_splits`.
        """
        return cls(LEMMA, key)

    @classmethod
    def pattern(cls, key: str) -> "Unit":
        return cls(PATTERN, key)

    @property
    def is_pattern(self) -> bool:
        return self.kind == PATTERN

    def __str__(self) -> str:
        return f"{self.kind}:{self.key}"
