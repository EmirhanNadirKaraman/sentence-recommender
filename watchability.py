"""How well a video plays when your hands are full.

Neither a command nor a page: both score videos, and when this lived inside
`commands.difficulty` the web importing it closed a loop — `web` imports
`commands`, `commands` imports `serve`, `serve` imports `web`. It only worked
because `main.py` happened to load the commands first.
"""
from __future__ import annotations

# What a video should be to watch without touching anything. Long enough to
# settle into, short enough to finish on a run; the corpus median is 11.1
# minutes, so this is where the material already is.
IDEAL_MINUTES = 10
SHORT_MINUTES = 0.06          # cost per minute under
LONG_MINUTES = 0.03           # cost per minute over — a long video is only
                              # a commitment, a short one is an interruption

# Comprehension for watching, not studying. Below this you are decoding
# rather than listening; at the very top there is nothing left to pick up.
COMFORTABLE = 0.95

# A video of five captioned lines scores wonderfully on comprehension for the
# same reason an empty page does. Below this it is not easy, it is empty.
ENOUGH_LINES = 40


def length_band(minutes: float | None) -> float:
    """How well a video's length sits, on its own, in [0, 1].

    Separate from `watchability` because the two are wanted apart. Watching
    asks whether you can follow a video at all, and squares comprehension to
    say so — which at eleven percent understood scores every video in the
    corpus at roughly zero, length included. Choosing which of several videos
    to open a sentence in is a different question, and there length is the
    part that still discriminates: it reaches zero at about forty-three
    minutes, which is most of what the reading page was landing in.

    A video whose duration was never recorded gets the same benefit of the
    doubt it gets in `watchability`.
    """
    if minutes is None:
        return 0.7
    if minutes < IDEAL_MINUTES:
        return max(0.0, 1 - (IDEAL_MINUTES - minutes) * SHORT_MINUTES)
    return max(0.0, 1 - (minutes - IDEAL_MINUTES) * LONG_MINUTES)


def watchability(comprehension: float, minutes: float | None,
                 lines: int = ENOUGH_LINES) -> float:
    """How well this plays with your hands full.

    Three bands multiplied. Comprehension decides whether you can follow it
    while running — below comfortable it drops off sharply, because a video
    you cannot follow is not a harder video, it is a different activity.
    Length is a gentler preference either side of ten minutes. And a video of
    five captioned lines scores wonderfully for the same reason an empty page
    does, so it is damped by how much is actually in it.
    """
    follow = min(comprehension / COMFORTABLE, 1.0)
    follow *= follow                      # squared: half-understood is far
                                          # worse than half as good
    return round(follow * length_band(minutes)
                 * min(lines / ENOUGH_LINES, 1.0), 4)
