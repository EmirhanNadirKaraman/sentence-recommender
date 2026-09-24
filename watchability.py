"""How well a video plays when your hands are full.

Neither a command nor a page: both score videos, and when this lived inside
`commands.difficulty` the web importing it closed a loop — `web` imports
`commands`, `commands` imports `serve`, `serve` imports `web`. It only worked
because `main.py` happened to load the commands first.
"""
from __future__ import annotations

# Named rather than spelled, so adding a taste cannot leave this file quietly
# weighing it at 1.0. `vocab.channel_taste` imports only `state`, so this does
# not reopen the loop the docstring above warns about.
from vocab.channel_taste import DOWN, MACHINE

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

# And how much of what was said has to survive filtering before the score
# describes the video rather than a fragment of it.
#
# `ENOUGH_LINES` was meant to cover this and only half does, because it counts
# the lines that survived rather than the share that did. A Peppa Pig episode
# whose track is largely English kept 46 of its 390 lines: past the forty-line
# bar, so nothing damped it, and it was scored as though those 46 were the
# whole episode -- which made it the *easiest* video in the corpus and the
# first thing the feed offered. 101 videos clear that bar while losing over
# half their dialogue.
#
# Half, because the typical video keeps far more: coverage runs 56% at the
# lower quartile, 69% median, 85% at the ninth decile. So this leaves an
# ordinary video alone and bites only where most of the talking is missing.
TYPICAL_COVERAGE = 0.5


# What subscribing and setting aside are worth, applied to a finished score
# rather than folded into it: watchability is a fact about the video and this
# is a fact about you, and keeping them apart is what lets taste be changed
# without rescoring anything.
#
# Four either way, which against the spread the corpus actually produces --
# the top eight videos run 0.073 down to 0.006 -- moves a channel several
# places without letting it own the feed. A set-aside channel still holds its
# order among its peers, so the one video on it that teaches the word you
# need is four times harder to reach, not gone. Nothing here is ever zero:
# `video_blacklist` is what removes something, and it takes a video at a
# time, deliberately.
SUBSCRIBED = 2.0
SET_ASIDE = 0.25


def taste_weight(taste: str | None) -> float:
    """The multiplier for what you have said about a channel. A channel
    marked machine-made sits where a set-aside one does: down, not out.

    `human` is deliberately 1.0 and not `SUBSCRIBED`: it records that the
    voice was listened to and found real, which is the absence of a fault
    rather than a reason to lift the channel over one nobody has judged yet.
    Falling through to the default would do the same thing silently; it is
    named here so that nobody later reads the omission as an oversight.
    """
    if taste == "up":
        return SUBSCRIBED
    if taste in (DOWN, MACHINE):
        return SET_ASIDE
    return 1.0                        # no opinion, or `human`


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


# What a level of the judge's costs a video, as a share — see `level_band`.
# The same fifth a card's sentence pays (`corpus.answers.LEVEL_COST`), read
# against the corpus on 2026-09-21: 1,536 watchable videos levelled from
# thirty lines each run from .21 (`200 Tägliche Aktivitäten auf Deutsch
# A1`) to 3.16 (`Anfechtungsklage & Nichtigkeitsklage`), median 2.04, a
# tenth under 1.48 and a tenth over 2.40 — 7 A1, 161 A2, 1,295 B1, 73 B2.
# At a fifth a level the easiest video keeps .96 and the median .59, so
# the band decides among videos comprehension cannot tell apart and does
# not overturn a video you can actually follow; at .3 a B2 video would keep
# .05 and be gone.
LEVEL_COST = 0.2


def level_band(level: float | None) -> float:
    """How well a video's German sits, on its own, in [0, 1].

    `level` is the judge's mean over a sample of the video's lines, in
    levels above A1 (`corpus.levels`). Lower is better, a fifth a level,
    as for the sentences a card shows: the reel is for a reader starting
    from nothing, and with two hundred words known comprehension is 2–20%
    everywhere and orders the feed by which videos happen to say those
    words. This is the difficulty that does not depend on the word count.
    None -- a video not yet levelled -- is left alone, and the caller
    hands such a video the typical level rather than None, or it would
    outrank every levelled one.
    """
    if level is None:
        return 1.0
    return max(0.0, 1.0 - LEVEL_COST * level)


def watchability(comprehension: float, minutes: float | None,
                 lines: int = ENOUGH_LINES,
                 dialogue: int | None = None,
                 level: float | None = None) -> float:
    """How well this plays with your hands full.

    Three bands multiplied. Comprehension decides whether you can follow it
    while running — below comfortable it drops off sharply, because a video
    you cannot follow is not a harder video, it is a different activity.
    Length is a gentler preference either side of ten minutes. And a video of
    five captioned lines scores wonderfully for the same reason an empty page
    does, so it is damped by how much is actually in it.

    `dialogue` is every line the subtitles hold, against `lines`, which is
    what survived filtering and is all `comprehension` was measured over. A
    video most of whose talking was dropped is not an easy video, it is a
    video being judged on the part that happened to parse -- see
    `TYPICAL_COVERAGE`. Omit it and nothing is damped, which is what every
    caller did before the fraction was available to them.

    `level` is the judge's level of the video, `level_band`; omitted,
    nothing is damped.
    """
    follow = min(comprehension / COMFORTABLE, 1.0)
    follow *= follow                      # squared: half-understood is far
                                          # worse than half as good
    covered = (min((lines / dialogue) / TYPICAL_COVERAGE, 1.0)
               if dialogue else 1.0)
    return round(follow * length_band(minutes)
                 * min(lines / ENOUGH_LINES, 1.0) * covered * level_band(level), 4)
