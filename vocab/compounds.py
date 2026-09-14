"""Compounds a reader can get from their parts.

German makes a new word out of every seam: someone who knows `krank` and
`das Haus` still meets `Krankenhaus` as a word they have never seen. That is
an artefact of writing rather than of vocabulary, and treating it as
vocabulary makes the roadmap teach a word nobody needs taught.

The correction is applied to what a reader *knows*, not to what a sentence
*says*. An earlier version rewrote sentences -- `Krankenhaus` became `krank`
plus `haus` -- which erased the compound as a unit and so made it impossible
to teach one directly. Expanding the known set instead can only ever add:

  the compound stays a unit, and stays teachable
  it becomes free the moment both parts are known
  no sentence changes, so no goal can be made unreachable
  and a wrong entry costs one compound known too early, not a word deleted

Only the checked half of `data/compounds.txt` is read. Below the marker the
file holds guesses, and about a third of them are wrong -- `hochzeit` splits
perfectly into `hoch` and `zeit` and means "wedding".

**One word can be two units**, and that is why a part is a *set* of units
rather than one. The study list writes a noun with its article, so `das Haus`
is the goal while the analyser also yields a bare `haus`; strict counting
then renames the bare form to the goal that teaches it, so the sentence says
`das Haus` and not `haus`. Resolving `haus` to the bare lemma alone found
nothing
where it mattered most: 187 of 231 parts disappear under strict, and the
whole hand-checked list granted two compounds instead of a hundred and
eighty. A part is satisfied by *any* unit meaning that word.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from vocab.entry import LEMMA, Unit

FILE = Path(__file__).resolve().parents[1] / "data" / "compounds.txt"
CHECKED_TO_HERE = "# ===================== CHECKED TO HERE ====================="


def read_pairs(path: Path = FILE) -> dict[str, tuple[str, ...]]:
    """The checked compounds, as written: lowercase strings.

    Stops at the marker. What is below it has not been read by a person, and
    the guesses there are wrong often enough to be worse than nothing.
    """
    if not path.exists():
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith(CHECKED_TO_HERE):
            break
        fields = raw.split("#", 1)[0].split("\t")
        if len(fields) >= 2 and fields[0].strip() and fields[1].split():
            out[fields[0].strip().lower()] = tuple(p.lower()
                                                   for p in fields[1].split())
    return out


# Written in front of a noun on the study list, and carrying no meaning of
# its own that a compound part could need.
ARTICLES = frozenset({"der", "die", "das", "den", "dem", "des", "ein", "eine"})


def _names_only(key: str, word: str) -> bool:
    """Whether a goal key names `word` and nothing else.

    `das Haus` does; `etw. (Akk) essen` and `jdm. (Dat) etw. (Akk) geben` do
    not, and neither does `der Vorsitzende, die Vorsitzende`. The test is
    deliberately strict, because a false positive here grants a compound to
    someone who has only learned a verb that shares its stem.
    """
    rest = [token for token in key.split() if token.lower() not in ARTICLES]
    return len(rest) == 1 and rest[0].lower() == word


class Compounds:
    """Which compounds a vocabulary already contains, without being told.

    An entry is `(whole, parts)` where `whole` is every unit naming the
    compound and each part is every unit naming that piece -- see the module
    docstring for why both are sets. The compound is derivable once every
    part has at least one of its units known, and granting it marks every
    unit in `whole`, since they are all the same word.

    Anything named by no unit at all is dropped. It could not fire, and
    keeping it would only make the numbers here look larger than the effect.
    """

    def __init__(self, entries: Iterable[tuple[frozenset, tuple]] = ()) -> None:
        self._entries = list(entries)
        # part unit -> the entries it is a piece of, so learning one word asks
        # about a handful of compounds rather than all of them.
        self._holding: dict[Unit, list[int]] = defaultdict(list)
        for index, (_, parts) in enumerate(self._entries):
            for alternatives in parts:
                for unit in alternatives:
                    self._holding[unit].append(index)
        self._whole: dict[Unit, int] = {}
        for index, (whole, _) in enumerate(self._entries):
            for unit in whole:
                self._whole[unit] = index

    @classmethod
    def over(cls, inventory: Iterable[Unit],
             pairs: Mapping[str, tuple[str, ...]] | None = None,
             covered_by: Mapping[str, frozenset] | None = None) -> "Compounds":
        """Resolve the file onto the units a corpus and a study list use.

        `covered_by` maps a written form to the goal units that teach it --
        `Application.covered_by`. Without it only the corpus's own lemmas are
        found, which is not enough under strict counting, where the goal has
        absorbed the bare form.
        """
        corpus: dict[str, set[Unit]] = defaultdict(set)
        for unit in inventory:
            if unit.kind == LEMMA:
                corpus[unit.key.lower()].add(unit)

        def units_for(word: str) -> frozenset[Unit]:
            found = set(corpus.get(word, ()))
            if found:
                # The capital marks the noun, and every entry in this file is
                # a compound noun whose parts carry their nominal sense:
                # `lebensqualität` is the quality of `Leben` the life, not of
                # `leben` the act of living. Spelled out rather than taken off
                # a sort, because capitals sort *first* in Python and `max`
                # picked the verb every time.
                nouns = sorted((u for u in found if u.key != u.key.lower()),
                               key=lambda u: u.key)
                found = {nouns[0]} if nouns else {
                    sorted(found, key=lambda u: u.key)[0]}
            # The goals that teach this word, whatever case the list wrote.
            # Only goals that name *just* this word: the list writes a noun
            # as `das Haus` and a verb as `etw. (Akk) essen`, both of them
            # pattern units, so the kind cannot tell them apart. Knowing how
            # to use a verb is not knowing the noun that heads `Mittagessen`
            # -- and `das Essen` is on the list separately, which is the one
            # that belongs here.
            for form in (word, word.capitalize()):
                found |= {u for u in (covered_by or {}).get(form, ())
                          if _names_only(u.key, word)}
            return frozenset(found)

        entries = []
        for word, pieces in (read_pairs() if pairs is None else pairs).items():
            whole = units_for(word)
            parts = [units_for(p) for p in pieces]
            if whole and all(parts):
                entries.append((whole, tuple(parts)))
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, unit: object) -> bool:
        return unit in self._whole

    def parts_of(self, unit: Unit) -> tuple[frozenset, ...]:
        index = self._whole.get(unit)
        return () if index is None else self._entries[index][1]

    def names_of(self, unit: Unit) -> frozenset:
        """Every unit naming the same compound as `unit`."""
        index = self._whole.get(unit)
        return frozenset() if index is None else self._entries[index][0]

    def _ready(self, index: int, known) -> bool:
        whole, parts = self._entries[index]
        return (not whole <= known
                and all(alternatives & known for alternatives in parts))

    def unlocked_by(self, learned: Unit, known) -> list[Unit]:
        """Every unit of every compound `learned` completes.

        `known` must already contain `learned`. Returns only units not in it
        yet, so a caller can add them and ask again -- a compound can be a
        part of another compound, and that chain has to run out rather than
        be assumed one deep.
        """
        out: list[Unit] = []
        for index in self._holding.get(learned, ()):
            if self._ready(index, known):
                out.extend(self._entries[index][0] - known)
        return out

    def derivable(self, known) -> set:
        """Every compound unit reachable from `known`, to a fixpoint."""
        have = set(known)
        found: set[Unit] = set()
        queue = [u for index in range(len(self._entries))
                 if self._ready(index, have)
                 for u in self._entries[index][0] - have]
        while queue:
            unit = queue.pop()
            if unit in have:
                continue
            have.add(unit)
            found.add(unit)
            queue.extend(self.unlocked_by(unit, have))
        return found
