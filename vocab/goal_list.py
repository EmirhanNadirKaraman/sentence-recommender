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

import re
import sys
from pathlib import Path

from vocab.loader import ARTICLES

from vocab.entry import Unit


# `jdm. (Dat) etw. (Akk) erzählen` — a verb written with the cases it governs.
# An article-and-noun entry like `das Russisch` carries no case marker and is
# not one of these, which is the whole reason the test is on the marker rather
# than on the last word.
# The case marker, or a bare placeholder. `von etw. absehen` governs a case
# without naming one, and matching only on `(Akk)` left it out — so `absehen`
# and `von etw. absehen` stayed two goals for one verb, each listed as blocked
# by the other, which is the deadlock this exists to prevent.
CASE_FRAME = re.compile(r"\((?:Akk|Dat|Gen)\)|\b(?:etw|jdn|jdm)\.")


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
        for unit in out + [Unit.exact(word) for word in wanted]:
            seen.setdefault(unit, None)
        return self._one_goal_per_verb(tuple(seen))

    @staticmethod
    def _one_goal_per_verb(units: tuple[Unit, ...]) -> tuple[Unit, ...]:
        """Drop a bare verb the list also names inside a case frame.

        The list writes `nennen` and it writes `jdn. (Akk) + Name (Akk)
        nennen`, and both become goals. They are one German word, so every
        sentence saying it carries two unknown units and can never be i+1 for
        either — 263 sentences for `nennen`, including "So nennt man das
        Fastenbrechen", one word away from readable and unreachable for ever.

        `covered_forms` cannot help. `_drop_duplicates` keeps a unit if it
        `in goals or unit.key not in covered`, and the bare verb is itself a
        goal, so the first test passes and it is never dropped. The
        duplicate-collapsing machinery only ever removes things off the list.

        The frame is the one that survives, because it teaches the verb and
        the cases it governs where the bare lemma teaches only the verb.

        Two guards. Only a case frame counts, or `das Russisch` would eat the
        adjective `russisch` and `der Morgen` the adverb `morgen` — the last
        word of an article-and-noun entry coincides with a different goal
        surprisingly often. And a capitalised bare goal is never dropped: the
        capital marks a noun that shares its lemma with a verb, which is a
        different word from the verb whatever the frame says.
        """
        frames = {u.key.split()[-1].lower() for u in units
                  if u.is_pattern and CASE_FRAME.search(u.key)}
        return tuple(u for u in units
                     if u.is_pattern
                     or u.key != u.key.lower()      # a noun, keeping its capital
                     or u.key not in frames)

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
