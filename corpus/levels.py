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
