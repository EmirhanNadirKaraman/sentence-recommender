"""Compounds a reader can get from their parts.

German makes a new word out of every seam: someone who knows `krank` and
`Haus` still meets `Krankenhaus` as a word they have never seen. That is an
artefact of writing rather than of vocabulary, and treating it as vocabulary
makes the roadmap teach a word nobody needs taught.

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
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

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


class Compounds:
    """Which compounds a vocabulary already contains, without being told.

    Built against the units a corpus actually uses, because the file is
    written in plain lowercase and the analyser is not: it keeps the capital
    on the handful of lemmas where it is the only thing separating a noun
    from its verb. `Essen` the meal and `essen` the verb are two units here,
    and `mittagessen` is Mittag plus the *noun*.

    So a part that exists in both cases resolves to the capitalised one. Every
    entry in this file is a compound noun, and its parts contribute their
    nominal sense -- `lebensqualität` is the quality of *Leben* the life, not
    of `leben` the act of living. Preferring the noun is also the cautious
    direction: it grants strictly less than accepting either case would.

    Anything the corpus never says is dropped. It could not fire, and keeping
    it would only make the numbers here look larger than the effect.
    """

    def __init__(self, parts: dict[Unit, tuple[Unit, ...]] | None = None) -> None:
        self._parts: dict[Unit, tuple[Unit, ...]] = dict(parts or {})
        # part -> the compounds it is a piece of, so learning one word asks
        # about a handful of compounds rather than all of them.
        self._holding: dict[Unit, list[Unit]] = defaultdict(list)
        for word, pieces in self._parts.items():
            for piece in set(pieces):
                self._holding[piece].append(word)

    @classmethod
    def over(cls, inventory: Iterable[Unit],
             pairs: dict[str, tuple[str, ...]] | None = None) -> "Compounds":
        """Resolve the file onto the lemmas `inventory` actually contains."""
        by_lower: dict[str, list[str]] = defaultdict(list)
        for unit in inventory:
            if unit.kind == LEMMA:
                by_lower[unit.key.lower()].append(unit.key)

        def pick(word: str) -> Unit | None:
            forms = by_lower.get(word)
            if not forms:
                return None
            # The capital marks the noun; see the class docstring. Spelled
            # out rather than taken off a sort, because capitals sort *first*
            # in Python and `max` therefore picked the verb every time.
            nouns = sorted(f for f in forms if f != f.lower())
            return Unit(LEMMA, nouns[0] if nouns else sorted(forms)[0])

        resolved: dict[Unit, tuple[Unit, ...]] = {}
        for word, pieces in (read_pairs() if pairs is None else pairs).items():
            whole = pick(word)
            found = [pick(p) for p in pieces]
            if whole is not None and all(f is not None for f in found):
                resolved[whole] = tuple(found)
        return cls(resolved)

    def __len__(self) -> int:
        return len(self._parts)

    def __contains__(self, unit: object) -> bool:
        return unit in self._parts

    def parts_of(self, unit: Unit) -> tuple[Unit, ...]:
        return self._parts.get(unit, ())

    def unlocked_by(self, learned: Unit, known) -> list[Unit]:
        """Compounds that `learned` completes, given everything else known.

        `known` must already contain `learned`. Returns only compounds not in
        it yet, so a caller can add them and ask again -- a compound can be
        a part of another compound, and that chain has to run out rather than
        be assumed one deep.
        """
        return [word for word in self._holding.get(learned, ())
                if word not in known
                and all(p in known for p in self._parts[word])]

    def derivable(self, known) -> set[Unit]:
        """Every compound reachable from `known`, to a fixpoint."""
        have = set(known)
        queue = [w for w, ps in self._parts.items()
                 if w not in have and all(p in have for p in ps)]
        found: set[Unit] = set()
        while queue:
            word = queue.pop()
            if word in have:
                continue
            have.add(word)
            found.add(word)
            queue.extend(self.unlocked_by(word, have))
        return found
