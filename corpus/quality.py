"""What makes an example sentence worth showing.

Separate from `filter.py` on purpose. The filter decides what belongs in the
corpus at all and runs before analysis, so it sees only text, and what it
rejects is gone. This ranks the survivors — a sentence can be perfectly good
German and still be a poor thing to learn a word from — and rejects nothing:
a word whose only example is four words long is still taught with it.

Lives here rather than in `experiments/` because the roadmap picks by it. The
experiments measure the same function the reader sees, so the history in
`experiment_results/` keeps describing what is actually being shown.
"""
from __future__ import annotations

import re

# Bump when the scale changes. Recorded against every experiment row, because
# a mean score from one definition cannot be compared with a mean from
# another — the history would show quality "improving" when only the ruler
# moved. It is also part of `current_stamp`, so a bump tells every stored
# roadmap that the corpus it was walked over is not the one here now.
#
# 4: the band's floor from eight words to five.
# 5: the band's ceiling from fifteen to twenty-five.
VERSION = 5

# Speech, not prose. Long enough to show the word doing something, short
# enough to hold in mind while reading it.
#
# The floor was eight, and eight was measured against prose intuition rather
# than against this corpus. Subtitle German peaks at five words a line and
# falls away from there monotonically, so the bar sat in the middle of the
# mass: it admitted 33% of 169,155 sentences, and the three lengths it cut
# off — five, six and seven — hold 75,171 of them between them.
#
# It also stranded goals the corpus does say. Of the 66 the b1 walk cannot
# reach, 24 have a sentence and every one of those sentences was refused for
# length alone: `Die Arbeitslosigkeit ist hoch und steigt weiter.` is seven
# words. Five is where `filter.py` already stops, so this admits everything
# that survived it and draws no second line of its own.
#
# Nothing is preferred for being short. `score` still peaks at 9-11 and
# tapers both ways, so a five-word sentence wins only where there is no
# longer one — which is the stranded case this exists for.
#
# The ceiling moved for the same reason and on the same evidence. At fifteen
# it refused every sentence there was for 63 goals the corpus does say — 74
# of those sentences were merely long, none was short — and raising it to
# twenty-five gives 52 of the 63 an example for 9% more of the corpus.
# Twenty-five rather than a rounder number because nothing here is longer:
# `filter.py` stops first, so this again draws no second line of its own.
#
# This is the asymmetry noted below, taken seriously. Falling short means
# missing context and teaching less; running long means being harder to
# read. The second is the cheaper error, and `score` charges for it anyway.
BAND = (5, 25)          # the binary bar: is this worth showing at all
IDEAL = (9, 11)         # equally good, and the tie is broken on merit

# Deliberately asymmetric, where it used to be so by accident: a sentence
# below the peak is missing context and teaches less, while one above it is
# merely harder to read. Falling short costs more per word than running long.
SHORT_PENALTY = 0.08
LONG_PENALTY = 0.06

TERMINAL = re.compile(r"[.!?]")
INTERNAL_BREAK = re.compile(r"[.!?]\s+\S")


def well_formed(text: str) -> bool:
    """One sentence, of a length worth reading."""
    words = len(text.split())
    return BAND[0] <= words <= BAND[1] and not INTERNAL_BREAK.search(text)


def variety(text: str) -> float:
    """Share of the words that are distinct.

    The tie-break, and not an arbitrary one: `Ja, ja, ja, das ist gut genug`
    and a sentence of eight different words score the same on length, and the
    second teaches more. Chosen over character length, which was the previous
    tie-break and simply reintroduced the bias the peak exists to remove.
    """
    words = [w.lower() for w in text.split()]
    return len(set(words)) / len(words) if words else 0.0


def score(text: str) -> float:
    """0..1, higher is better. A narrow plateau, tie broken on merit.

    Two earlier shapes were wrong in opposite directions. A wide plateau of
    eight to twelve, with the tie broken on character length, put forty-seven
    percent of the roadmap on exactly eight words — the shortest-wins bias
    relocated rather than removed. A single peak at ten was worse: fifty-eight
    percent landed on exactly ten, because with thirteen candidates a step
    there is nearly always one of the single best length, so it wins every
    time. A peak concentrates harder than a plateau.

    Three lengths score alike, and `variety` decides between them, which
    spreads the choice on something that is actually a quality rather than on
    a proxy for length.

    Tapered rather than cut: a word whose only example is six words long is
    still taught with it, just ranked below a better one.
    """
    words = len(text.split())
    if words < IDEAL[0]:
        length = max(0.0, 1 - (IDEAL[0] - words) * SHORT_PENALTY)
    elif words > IDEAL[1]:
        length = max(0.0, 1 - (words - IDEAL[1]) * LONG_PENALTY)
    else:
        length = 1.0
    if INTERNAL_BREAK.search(text):
        length *= 0.5
    return length
