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

from vocab.loader import ARTICLES

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

    @staticmethod
    def corrections(path: Path) -> dict[str, str]:
        """Entries the parser mis-lemmatises when it sees them alone.

        Keyed on the entry as the study list writes it. Hand-checked rather
        than derived: the parser's other rewrites of these same entries are
        corrections — "im" to "in", "geboren" to "gebären" — and no rule
        separates those from the damage.
        """
        out: dict[str, str] = {}
        if not path.exists():
            return out
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if "\t" not in line:
                continue
            entry, fix = (part.strip() for part in line.split("\t", 1))
            if entry and fix:
                out[entry] = fix
        return out

    def units(self, patterns: frozenset[str], lemmatise=None,
              corrections: dict[str, str] | None = None) -> tuple[Unit, ...]:
        """The goals as units, in list order.

        `patterns` is the registered pattern vocabulary — `phrase_table`'s
        canonicals. An entry in it is a pattern and is kept verbatim, because
        that string is exactly what the matcher emits.

        Everything else is a word, and taking it verbatim was wrong. The list
        writes a word the way a dictionary does, which is not the way the
        parser lemmatises it:

          "der, die, das"  one entry naming three words
          "das Leben"      an article the parser does not keep
          "im", "erste"    forms the parser reduces to "in" and "erst"

        Each of those became a goal that no sentence could ever satisfy — 202
        of them, a fifth of what was left to learn, unreachable no matter how
        much video was added. Alternatives are split, articles dropped, and
        `lemmatise` maps what remains into the parser's own lemma space.
        Without it the old literal reading is kept, so this stays usable
        without loading a parser.
        """
        corrections = corrections or {}
        wanted: list[str] = []
        settled: dict[int, str] = {}
        out: list[Unit] = []
        for entry in self.entries():
            if entry in patterns:
                out.append(Unit.pattern(entry))
                continue
            fix = corrections.get(entry)
            if fix is not None:
                settled[len(wanted)] = fix
                wanted.append(fix)
                continue
            wanted.extend(self._alternatives(entry))

        if lemmatise is not None:
            lemmas = lemmatise(wanted)
            wanted = [settled.get(i) or lemmas[i] for i in range(len(wanted))]
            wanted = [lemma for lemma in wanted if lemma]
        seen: dict[Unit, None] = {}
        for unit in out + [Unit.lemma(word) for word in wanted]:
            seen.setdefault(unit, None)
        return tuple(seen)

    @staticmethod
    def _alternatives(entry: str) -> list[str]:
        """One entry, as the separate words it actually names."""
        out: list[str] = []
        for part in entry.split(","):
            words = part.split()
            if len(words) > 1 and words[0].lower() in ARTICLES:
                words = words[1:]          # "das Leben" -> "Leben"
            if words:
                out.append(" ".join(words))
        return out
