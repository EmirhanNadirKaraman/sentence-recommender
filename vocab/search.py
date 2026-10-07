"""Finding a word in the corpus's vocabulary, misspellings included.

A list built by searching needs a box that forgives: the reader half-knows
the word, which is why they are looking it up. Exact matching answers only
for words they could already spell.

The vocabulary comes from materialized unit counts. A trigram posting index
narrows fuzzy scoring for live queries; cached lowercase strings preserve
substring matching, even for short queries. The immutable index is reused
instead of loading sentences or adding a database extension per keystroke.
"""
from __future__ import annotations

from collections import Counter
from heapq import nsmallest

from vocab.entry import Unit


def word_families(units, language: str = "de") -> dict[Unit, tuple[Unit, ...]]:
    """Dictionary rows, with grammar usages nested under their lexical head.

    This is presentation grouping, not a knowledge alias: knowing a verb
    does not grant knowledge of its prepositions or reflexive constructions.
    Multiword expressions and ambiguous heads keep their own rows.
    """
    from vocab.aliases import heads
    units = tuple(units)
    lemmas = {u.key: u for u in units if u.kind == "lemma"}
    folded = {}
    for key, unit in lemmas.items():
        folded.setdefault(key.casefold(), []).append(unit)
    families = {}
    for unit in units:
        parent = unit
        if unit.kind == "pattern":
            named = heads(unit.key, language)
            if len(named) == 1:
                head = next(iter(named))
                matches = folded.get(head.casefold(), ())
                parent = lemmas.get(head) or (matches[0] if len(matches) == 1 else unit)
        families.setdefault(parent, []).append(unit)
    return {parent: tuple(sorted(members, key=lambda u: (u != parent, u.key, u.kind)))
            for parent, members in families.items()}


def trigrams(text: str) -> set[str]:
    """`haus` -> {'  h', ' ha', 'hau', 'aus', 'us '}.

    Padded, so a short word still yields enough to score and so the start of
    a word counts for more than its middle — which is where a reader's
    memory of a word is usually soundest.
    """
    padded = f"  {text.strip().lower()} "
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


class UnitSearch:
    """The corpus's units, searchable by approximate spelling."""

    def __init__(self, counts: Counter, rename=None) -> None:
        # (kind, key) -> how often it is said. The count is the tie-break:
        # between two equally close spellings the commoner word is nearly
        # always the one being looked for.
        self._origins = {}
        for kind, key in counts:
            raw = Unit(kind, key)
            named = rename(raw) if rename else raw
            self._origins.setdefault(named, set()).add(raw)
        if rename is not None:
            normalized = Counter()
            for (kind, key), count in counts.items():
                unit = rename(Unit(kind, key))
                normalized[(unit.kind, unit.key)] += count
            counts = normalized
        self._said = dict(counts)
        self._grams: dict[tuple[str, str], set[str]] = {
            key: trigrams(key[1]) for key in self._said}
        self._lower = {key: key[1].lower() for key in self._said}
        self._postings = {}
        for key, grams in self._grams.items():
            for gram in grams:
                self._postings.setdefault(gram, set()).add(key)

    def contains(self, unit: Unit) -> bool:
        return (unit.kind, unit.key) in self._said

    def originals(self, units) -> frozenset[Unit]:
        return frozenset(raw for unit in units for raw in self._origins.get(unit, (unit,)))

    def exact(self, key: str) -> Unit | None:
        # Saved lists use canonical strings. A registered pattern wins over
        # a same-spelled lemma, matching GoalList's resolution.
        for kind in ("pattern", "lemma"):
            if (kind, key) in self._said:
                return Unit(kind, key)
        return None

    def __len__(self) -> int:
        return len(self._said)

    def find(self, needle: str, limit: int = 20,
             floor: float = 0.3) -> list[tuple[Unit, int, float]]:
        """Closest first, as (unit, times said, similarity 0..1).

        A substring match scores 1.0 outright: someone typing `haus` wants
        `das Haus` before anything merely similar, and Jaccard alone ranks
        the exact word below shorter near-misses because the padding
        dominates a short string.
        """
        wanted = needle.strip().lower()
        if not wanted:
            return []
        target = trigrams(wanted)
        scored = []
        candidates = set().union(*(self._postings.get(g, ()) for g in target))
        # Substrings still win outright, including one/two-letter queries
        # whose padded trigrams need not occur inside the candidate word.
        candidates.update(key for key, low in self._lower.items() if wanted in low)
        for kind, key in candidates:
            grams = self._grams[(kind, key)]
            low = self._lower[(kind, key)]
            if wanted in low:
                score = 1.0
            else:
                shared = len(target & grams)
                if not shared:
                    continue
                score = shared / len(target | grams)
                if score < floor:
                    continue
            scored.append((score, self._said[(kind, key)], kind, key))
        # Short live queries can match tens of thousands of words. Keep only
        # the best few and construct Unit objects for those, not every match.
        best = nsmallest(max(0, limit), scored, key=lambda row: (-row[0], -row[1], row[3], row[2]))
        return [(Unit(kind, key), said, round(score, 3))
                for score, said, kind, key in best]
