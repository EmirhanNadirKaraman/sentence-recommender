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

# How close two videos have to be in difficulty before the ranking stops
# caring, in unknown words per sentence. Whole words, because that is the unit
# the number is in and a tenth of a word is not a difference anyone could act
# on -- and because a finer band would leave nothing for the length key below
# to decide, which is still doing useful work.
GAP_BAND = 0


def gaps_by_video(sentences, known: frozenset[Unit]) -> dict[str, float]:
    """Mean unknown units per sentence, per video.

    How hard the material *around* a sentence is. Comprehension -- the share
    of a video that reads cleanly -- cannot answer this yet and will not for a
    long time: measured against the current vocabulary, more than half of all
    videos have not one fully readable sentence, so it is zero for the median
    video and a key built on it would sort nothing. This still separates them.
    Of the 1,378 videos with no readable sentence at all, the mean gap runs
    from 2.38 to 9.04.
    """
    totals: dict[str, list] = {}
    for s in sentences:
        if s.timing:
            slot = totals.setdefault(s.timing.video_id, [0, 0])
            slot[0] += len(s.units - known)
            slot[1] += 1
    return {video: unknown / lines for video, (unknown, lines) in totals.items()
            if lines}


def rank(unit: Unit, known: frozenset[Unit],
           minutes: dict[str, float] | None = None,
           gaps: dict[str, float] | None = None,
           verdicts: dict[str, float] | None = None):
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

    `gaps` maps a video to how many unknown words its sentences average, and
    when given, a sentence surrounded by material closer to the reader's level
    wins a tie. A sentence can be perfectly i+1 and sit in a video where every
    other line is hopeless, and nothing here used to notice. It is banded to
    whole words and placed after quality for the same reason length is: a
    strong key here buys a shorter, easier video by giving up the sentence
    itself, and the weak key gets most of the benefit for none of the cost.

    Not comprehension, which is the obvious measure and a dead one. See
    `gaps_by_video`.

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
    def verdict(s) -> float:
        """What someone thought of this sentence, or no opinion.

        Absent means unjudged, which scores as 1.0 — the best — so adding
        this reorders nothing that has not been marked. Only a sentence
        somebody has actually called bad moves, and it moves down.
        """
        return 1.0 if verdicts is None else verdicts.get(s.text, 1.0)

    def video_fit(s) -> float:
        # No lengths to hand means no preference, so every sentence ties here
        # and the ranking is exactly what it was before.
        if minutes is None or s.timing is None:
            return 0.0
        return length_band(minutes.get(s.timing.video_id))

    def video_gap(s) -> float:
        # Unknown means no preference, and it has to sort *last* among the
        # bands rather than first: a video nothing is known about is not an
        # easy one. Ascending, because fewer unknown words is better.
        if gaps is None or s.timing is None:
            return 0.0
        found = gaps.get(s.timing.video_id)
        return float("inf") if found is None else round(found, GAP_BAND)

    return lambda s: (len(s.units - known - {unit}),
                      # Above quality, and deliberately. `quality` reads the
                      # text and can only see length and variety; a verdict
                      # is someone having noticed that the sentence is
                      # broken in a way the characters do not show — a
                      # transcription error like `die Verlet`, which scores
                      # as an ordinary sentence and is not one. Known-bad
                      # should lose to merely-thought-worse.
                      -verdict(s),
                      s.translation is None,
                      -quality(s.text),
                      video_gap(s),
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
        minutes: dict[str, float] | None = None,
        gaps: dict[str, float] | None = None,
        verdicts: dict[str, float] | None = None,
    ) -> list[Sentence]:
        """The `limit` most readable sentences using `unit`, by `rank`.

        `minutes` and `gaps` are the maps the walk ranks with, and are passed
        rather than assumed: `rank` says the stored order has to be the order
        this would have produced, and for a long time it was not. This ranked
        without either, so 61 of 400 units opened on a different sentence
        depending on whether the page was served from the store or rebuilt
        from the corpus, on videos a median 16.6 minutes long against the
        walk's 14.3.

        `verdicts` is the same bargain: what a reader or a model has said
        about particular sentences, passed rather than looked up, so the
        walk and the page rank alike. Left out here once, and the third term
        of the key would differ between them for every sentence anybody had
        marked.

        `gaps` has to be measured over a whole corpus, so the listings built
        from `holding=` — every sentence saying one word, and nothing else —
        pass only `minutes`. A mean taken over that slice would not be the
        video's difficulty, it would be the difficulty of the lines that
        happen to contain this word.
        """
        candidates = self._by_unit.get(unit, ())
        return sorted(candidates,
                      key=rank(unit, known, minutes, gaps, verdicts))[:limit]
