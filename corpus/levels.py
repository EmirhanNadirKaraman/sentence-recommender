"""A video's level, from a sample of its lines.

The reel ranks by how many of a video's words you know, and with two
hundred words known that is 2–20% everywhere — an order made of which
videos happen to say your words. The judge's `level` is a difficulty that
does not depend on your word count, and it costs per line, so a video is
levelled from a fixed sample of its lines rather than all of them: thirty
lines put the mean within about a tenth of a level, at a thirtieth of the
price of the video.

The sample is drawn the same way every time — seeded by the video, over
its lines in text order — so a resumed pass asks the same lines, and the
level read back is the mean over that same sample rather than over every
line anyone ever levelled, which would tilt towards the plan's picks, the
easiest lines the video has.

The draw depends on the whole pool, and that is its weakness: a line
hidden, a rebuilt corpus or a re-run of `detect-language` changes the
pool and re-rolls the sample, and thirty out of a hundred and thirty
re-drawn keeps about seven of the old thirty — under `ENOUGH`, so the
video reads as unlevelled until the pass is run again (about twenty-three
lines, half a cent). Visible, not silent: the reel scores such a video at
the typical level and shows none. A pool-independent draw — the thirty
lines with the smallest hash of video and text — would not re-roll, and
is the rule to adopt the next time every video is levelled anyway; switching
now would re-roll all 1,536 at once, and the lines already levelled are
mostly not the ones it would pick.
"""
from __future__ import annotations

import random

SAMPLE = 30


def sample(video_id: str, texts, n: int = SAMPLE) -> list[str]:
    """`n` of the video's lines, the same `n` every time."""
    ordered = sorted(set(texts))
    if len(ordered) <= n:
        return ordered
    return random.Random(video_id).sample(ordered, n)

# How many of the sample must be levelled before the mean is trusted. A
# video half of whose thirty are in is within a seventh of a level; fewer
# than that is a guess wearing a number.
ENOUGH = SAMPLE // 2


def video_level(judged, video_id: str, texts, n: int = SAMPLE) -> float | None:
    """The video's level: the mean of the judge's expectation over its
    sample, in levels above A1, or None until enough of the sample is in."""
    found = [judged.expected(text) for text in sample(video_id, texts, n)]
    found = [level for level in found if level is not None]
    if len(found) < min(ENOUGH, n):
        return None
    return sum(found) / len(found)

