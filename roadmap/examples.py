"""Finding example sentences for a unit at review time.

Kept separate from `CorpusIndex` on purpose.  That index is mutated as the
greedy walk advances, so by the time step 12 is reviewed its state has moved
on; this one is read-only and built over the finished corpus, so it can be
queried at any point with whatever the learner knows *now*.
"""
from __future__ import annotations

from collections import defaultdict

from corpus.quality import score as quality, variety
from corpus.sentence import Sentence
from vocab.entry import Unit
from watchability import length_band

# How many sentences a reader is given to step through for one unit.  Lives
# here rather than beside the page because the walk stores a deck of this size
# with every step, and a page that showed a different number would be asking
# for sentences that were never written down.
DECK_SIZE = 24


def rank(unit: Unit, known: frozenset[Unit],
         minutes: dict[str, float] | None = None):
    """How example sentences for `unit` are ordered.

    Readability first, because an example is only useful if the learner can
    read the rest of it, and a translation after that — it makes an otherwise
    opaque sentence usable.  Then quality.

    Quality, and not length.  Length was the original third key, and with no
    translations in the subtitle corpus the second key never fires, so the
    ranking was in practice "the shortest sentence that is readable".  For
    `all, alle` — a pattern in 2,223 sentences — that is `H, wo sind die
    alle?`, a five-word fragment with a name cut off the front of it, chosen
    over nine-word sentences that say something.  The walk's own example
    picker hit exactly this and was moved to quality; the deck kept it.

    `minutes` maps a video to its length, and when given, a sentence from a
    better-sized video wins a tie. It breaks ties rather than outranking
    quality on purpose: the reading page was opening on videos of a median
    thirty-eight minutes, and sorting on length first brings that to twelve —
    but sorting on it *after* quality already brings it to fifteen, and does
    it without giving up a thousandth of sentence quality. Ties on quality
    are plentiful, so the weaker key is doing almost all the work the strong
    one would, for nothing.

    Shared with the walk, which stores a deck with every step: the stored
    order has to be the order this ranking would have produced, or a page
    served from the store opens on a different sentence than one served from
    the corpus.
    """
    def video_fit(s) -> float:
        # No lengths to hand means no preference, so every sentence ties here
        # and the ranking is exactly what it was before.
        if minutes is None or s.timing is None:
            return 0.0
        return length_band(minutes.get(s.timing.video_id))

    return lambda s: (len(s.units - known - {unit}),
                      s.translation is None,
                      -quality(s.text),
                      -video_fit(s),
                      -variety(s.text),
                      s.text)


class ExampleIndex:
    """Every sentence containing a given unit, ranked for usefulness."""

    def __init__(self, sentences: list[Sentence]) -> None:
        self._by_unit: dict[Unit, list[Sentence]] = defaultdict(list)
        for sentence in sentences:
            for unit in sentence.units:
                self._by_unit[unit].append(sentence)

    def count(self, unit: Unit) -> int:
        return len(self._by_unit.get(unit, ()))

    def examples(
        self,
        unit: Unit,
        known: frozenset[Unit],
        limit: int = 3,
    ) -> list[Sentence]:
        """The `limit` most readable sentences using `unit`, by `rank`."""
        candidates = self._by_unit.get(unit, ())
        return sorted(candidates, key=rank(unit, known))[:limit]
