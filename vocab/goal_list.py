"""The list you actually mean to learn.

The default roadmap has no destination: it walks wherever the corpus is
easiest, which makes every sentence readable eventually but says nothing
about *which* words you get. A goal list turns that around — here is the
vocabulary I want, order it for me.

Read from a two-column tab-separated file. The first column is a lemma, the
second the blueprint it belongs to:

    haben       etw./jdn. (Akk) haben
    werden      werden

The second column is the one that matters, because it is what the matcher and
`phrase_table` both speak. Entries that name a registered pattern become
pattern units; the rest become plain lemmas.
"""
from __future__ import annotations

import sys
from pathlib import Path

from vocab.entry import Unit


class GoalList:
    """A target vocabulary, resolved into the units the roadmap deals in."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def entries(self) -> tuple[str, ...]:
        """Column two, in file order, de-duplicated.

        Order is kept because these files are written most-useful-first, and
        that is the only ranking a goal list carries.
        """
        if not self._path.exists():
            print(f"warning: no goal list at {self._path}", file=sys.stderr)
            return ()
        seen: dict[str, None] = {}
        for raw in self._path.read_text(encoding="utf-8").splitlines():
            columns = raw.split("\t")
            if len(columns) < 2:
                continue
            entry = columns[1].strip()
            if entry:
                seen.setdefault(entry, None)
        return tuple(seen)

    def units(self, patterns: frozenset[str]) -> tuple[Unit, ...]:
        """The goals as units, in list order.

        `patterns` is the registered pattern vocabulary — `phrase_table`'s
        canonicals. An entry in it is a pattern; anything else is a word,
        lowercased to match how lemmas are keyed.
        """
        return tuple(
            Unit.pattern(entry) if entry in patterns else Unit.lemma(entry)
            for entry in self.entries()
        )
