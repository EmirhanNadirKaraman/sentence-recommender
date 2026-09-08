"""When a sentence is spoken."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Timing:
    """The span of video a sentence covers, in seconds from the start."""

    video_id: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)

    def clock(self, seconds: float) -> str:
        """`HH:MM:SS.mmm`, the timestamp format WebVTT wants."""
        milliseconds = round(seconds * 1000)
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        secs, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"

    def cue(self) -> str:
        return f"{self.clock(self.start)} --> {self.clock(self.end)}"


@dataclass(frozen=True)
class TimedWord:
    """One word of the original subtitles, with the moment it is spoken.

    Subtitle rows carry a start and a duration but no word-level timing, so
    each row's span is shared out among its words in proportion to their
    length.  That is an approximation, but a row is a few seconds long and
    holds a handful of words, so the error stays well under a second — small
    enough for the overlay to land on the right line.
    """

    text: str
    start: float
    end: float
