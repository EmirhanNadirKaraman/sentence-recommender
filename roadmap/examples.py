"""Finding example sentences for a unit at review time.

Kept separate from `CorpusIndex` on purpose.  That index is mutated as the
greedy walk advances, so by the time step 12 is reviewed its state has moved
on; this one is read-only and built over the finished corpus, so it can be
queried at any point with whatever the learner knows *now*.
"""
from __future__ import annotations

import re
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
           verdicts: dict[str, float] | None = None,
           judged=None):
    """How example sentences for `unit` are ordered.

    Readability first, because an example is only useful if the learner can
    read the rest of it. Then what anyone has said about the sentence — see
    `verdicts`, and `judged` — and then quality.

    `judged` is what the corpus pass's judge answered (`corpus.answers`):
    per sentence, whether it stands alone, is complete, standard and well
    formed; per sentence and unit, whether the word is the word itself and
    how much the sentence gives it away. It multiplies into the same term
    as `verdicts`, and for the same reason it sits above quality: `quality`
    reads characters, and a judge has read the sentence. A sentence nobody
    has judged scores 1.0 there, so an empty store reorders nothing.

    There is no key for whether the corpus shipped a translation. There was
    one, second, above quality, and it was right while a translation was
    scarce: 85 sentences of 11,398 had one, and it was the only English a
    reader would ever see. Once `gloss-deck` translated every sentence the
    field stopped saying anything about what the reader gets and went on
    deciding anyway — see the note beside the key itself for what that did to
    step 48.

    Quality, and not length.  Length was the original third key, and with no
    translations in the subtitle corpus the second key never fired, so the
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
        somebody has actually called bad moves, and it moves down. The
        judge's answers multiply in the same way: worth showing at all,
        times worth showing for this word.
        """
        said = 1.0 if verdicts is None else verdicts.get(s.text, 1.0)
        if judged is not None:
            said *= judged.sentence(s.text) * judged.unit(s.text, unit)
        return said

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
                      -quality(s.text),
                      # No term for whether the corpus shipped a translation,
                      # and its removal is the point rather than an omission.
                      # It used to sit *above* quality, which was right while
                      # a translation was scarce and the only English anyone
                      # would see: 85 sentences of 11,398 had one. Left there
                      # once `gloss-deck` existed it decided outright — step
                      # 48 showed three sentences scoring 0.644, 0.644 and
                      # 0.532, two trailing off mid-thought and one starting
                      # lowercase, while twenty-one scoring 1.000 sat unused
                      # behind them for no better reason than that the bad
                      # three came with subtitles.
                      #
                      # Demoting it below quality fixed that and was still
                      # wrong. `score` plateaus — 80% of the sentences shown
                      # score exactly 1.000 — so quality ties constantly and
                      # the term went on deciding which of many equally good
                      # sentences a reader saw. What it selects for is which
                      # video happened to ship subtitles, which is a fact
                      # about the source and not about the sentence; 3.9% of
                      # the corpus has one, so it steered the whole deck into
                      # that slice. The English is generated for every
                      # sentence now, so the field tells a reader nothing.
                      video_gap(s),
                      -video_fit(s),
                      -variety(s.text),
                      s.text)


# --- telling two examples apart ------------------------------------------
#
# Three sentences that all say `auf jeden Fall` teach one collocation three
# times, not one word three ways. The card for `der Fall` opened on exactly
# that, while `Das wäre der Fall, wenn es Schengen nicht mehr gäbe.` and `Im
# Fall von George Floyd ...` sat unused further down its own candidate list.
#
# A second failure looks nothing like it from outside and falls to the same
# machinery: `Ech find', die machen es einem sehr einfach, die Menschen da.`
# beside `Ich find', ...` is one line twice, differing by a letter of
# dialect. Two cards in the plan showed a sentence next to a character-for-
# character copy of itself.
#
# Word trigrams answer both. The collocation test asks whether a trigram
# *containing the taught word* is shared, which is exactly what `auf jeden
# Fall` is and what `wäre der Fall` is not. The duplicate test asks how much
# the two sentences overlap overall.
#
# Measured over the 3,807 beginner cards showing more than one example: 264
# (6.9%) repeat a collocation and 27 (0.7%) carry a near-copy. Overlap is
# sharply bimodal -- 98.4% of the 11,181 pairs score under 0.1, and nothing
# at all falls between 0.6 and 0.7 -- so this threshold sits in an empty gap
# rather than cutting through a crowd.
ALIKE = 0.4

# Meaning, where the words themselves give nothing away. `Du würdest doch mich
# nicht töten, deinen Freund Frank.` and `Du würdest doch nicht deinen alten
# Freund Frank Bimbel töten.` are one sentence said twice: they share no
# trigram holding the taught word, and their overall overlap is 0.46, just
# under the line above.
#
# The vectors come from `corpus.vectors`, written by `embed-sentences`, and
# are of the sentence with the taught word *removed*. That word is in every
# candidate by construction, so it says nothing about whether two contexts
# differ and it pulls all of them together: on `der Vater` the gap between a
# repeated frame and a genuinely different one was 0.009 before masking and
# 0.065 after.
#
# spaCy's static vectors were tried here first and withdrawn. They scored the
# two `bekommen` sentences that are both about failing a class at 0.480 —
# and a completely different sense of the same word at 0.480 as well. No
# discrimination at all, because the link runs through `6` and `Sechs`
# meaning a bad grade, which is not in a word vector.
#
# 0.55 because that is what it takes to catch the case this was built for.
# Measured over the deck's 11,179 pairs the mean is 0.343 and the median
# 0.337, so the line sits far out in the tail: it flags 4.29% of cards, and
# the pair that prompted it scores 0.583.
SAME_TOPIC = 0.55

_VECTORS: dict[str, "object"] | None = None


def _known_vectors() -> dict:
    """Every stored sentence vector, read once.

    Loaded lazily rather than at import: most callers of this module never
    compare two sentences, and a corpus with no vectors yet must still rank.
    An empty store simply means this test never fires.
    """
    global _VECTORS
    if _VECTORS is None:
        from config import Settings                         # noqa: PLC0415
        from corpus.vectors import VectorStore              # noqa: PLC0415

        _VECTORS = VectorStore(Settings().state_path).load()
    return _VECTORS


# Digits included, unlike everywhere else in this project that splits German
# into words. `eine 6 bekommen` is the collocation being repeated, and dropping
# the numeral left `eine bekommen` beside `eine bekommen` with a different word
# between them — so the card that prompted this rule went on showing three
# sentences about the same failing grade.
_WORD = re.compile(r"[^\W_]+")


def _trigrams(text: str) -> set[tuple[str, ...]]:
    words = [word.lower() for word in _WORD.findall(text)]
    return {tuple(words[at:at + 3]) for at in range(len(words) - 2)}


def _head(sentence: Sentence, unit: Unit) -> str:
    """The taught word as this sentence spells it.

    Taken from the sentence's own surface rather than from the unit's key,
    because they differ exactly where it matters: `der Mensch` appears as
    `die Menschen`, and a trigram search for `mensch` would not find it.
    """
    for held, surface in sentence.surfaces:
        if held == unit and surface:
            return surface.lower().split()[-1]
    return unit.key.lower().split()[-1]


def spread(ordered: list[Sentence], unit: Unit, limit: int) -> list[Sentence]:
    """The best `limit` examples that are not each other.

    Greedy down the ranked list, so the first choice is still whatever `rank`
    put first: the sentence a step is taught with does not move, and only the
    ones beside it do.

    Anything rejected is kept and used to fill up at the end. A card showing
    three examples where two repeat is worse than three that do not, but it
    is better than a card showing one: where the corpus says a word one way
    and one way only, the repetition is the truth about the corpus, and the
    card should still be full.

    The exception is a sentence the card already carries, word for word. That
    is not a thin corpus being honest, it is the same row twice -- the same
    line said in two videos, or imported from two builds -- and a second copy
    of it teaches nothing at all. So the fill skips exact repeats and the
    card comes back short, which is the honest shape for a word the corpus
    says once.
    """
    if limit <= 1:
        return ordered[:limit]
    grams: dict[int, set[tuple[str, ...]]] = {}
    heads: dict[int, str] = {}

    def alike(one: Sentence, two: Sentence) -> bool:
        for sentence in (one, two):
            key = id(sentence)
            if key not in grams:
                grams[key] = _trigrams(sentence.text)
                heads[key] = _head(sentence, unit)
        first, second = grams[id(one)], grams[id(two)]
        if not first or not second:
            # Too short to have a trigram at all, so nothing to compare on
            # but the text itself.
            return one.text == two.text
        shared = first & second
        word = heads[id(one)]
        if any(word in gram for gram in shared):
            return True                 # the same collocation twice
        if len(shared) / len(first | second) >= ALIKE:
            return True                 # nearly the same words
        # Last, and only where both sentences have been embedded: two that
        # share neither a collocation nor their wording can still be one
        # sentence rewritten, or two ways of saying the same thing.
        import numpy                                       # noqa: PLC0415

        stored = _known_vectors()
        left, right = stored.get(one.text), stored.get(two.text)
        if left is None or right is None:
            return False
        return float(numpy.dot(left, right)) >= SAME_TOPIC

    chosen: list[Sentence] = []
    spare: list[Sentence] = []
    for sentence in ordered:
        if len(chosen) >= limit:
            break
        if any(alike(sentence, taken) for taken in chosen):
            spare.append(sentence)
        else:
            chosen.append(sentence)
    seen = {sentence.text for sentence in chosen}
    for sentence in spare:
        if len(chosen) >= limit:
            break
        if sentence.text in seen:
            continue
        seen.add(sentence.text)
        chosen.append(sentence)
    return chosen


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
        judged=None,
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
        return spread(sorted(candidates,
                             key=rank(unit, known, minutes, gaps, verdicts, judged)),
                      unit, limit)
