"""Finding a word in the corpus's vocabulary, misspellings included.

A list built by searching needs a box that forgives: the reader half-knows
the word, which is why they are looking it up. Exact matching answers only
for words they could already spell.

Trigrams rather than `pg_trgm`. Migration dd0d9cf4b307 declined the
extension because nothing issued a fuzzy query, and the first query that
does should reopen that decision rather than step past it — but not yet, on
this evidence: `unit_counts` hands back all 46,433 units off a materialized
view in 59ms, and scoring that many short strings in Python is cheaper than
a round trip. If the vocabulary grows an order of magnitude, or the search
starts running per keystroke against the whole corpus rather than its
units, that is the reason to go back to the extension.
"""
from __future__ import annotations

from collections import Counter

from vocab.entry import Unit


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

    def __init__(self, counts: Counter) -> None:
        # (kind, key) -> how often it is said. The count is the tie-break:
        # between two equally close spellings the commoner word is nearly
        # always the one being looked for.
        self._said = dict(counts)
        self._grams: dict[tuple[str, str], set[str]] = {
            key: trigrams(key[1]) for key in self._said}

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
        scored: list[tuple[float, int, Unit]] = []
        for (kind, key), grams in self._grams.items():
            low = key.lower()
            if wanted in low:
                score = 1.0
            else:
                shared = len(target & grams)
                if not shared:
                    continue
                score = shared / len(target | grams)
                if score < floor:
                    continue
            scored.append((score, self._said[(kind, key)], Unit(kind, key)))
        scored.sort(key=lambda row: (-row[0], -row[1], row[2].key))
        return [(unit, said, round(score, 3))
                for score, said, unit in scored[:limit]]
