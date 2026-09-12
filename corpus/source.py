"""Reads raw subtitle rows out of the shared database, grouped by video."""
from __future__ import annotations

from itertools import groupby

from corpus.sentence import RawLine

# Who wrote the subtitles a build is assembled from.
#
# A build name has always carried *how* its sentences were made — `subtitle`
# is the rejoined caption rows, `subtitle:llm` the same lines repaired by the
# local model. `video.transcript_source` carries *who wrote them*, and until
# there were machine tracks in the catalogue the two never had to be
# distinguished: every row was `manual`, and this query took whatever it
# found.
#
# That is exactly the join that made the separation load-bearing rather than
# cosmetic. `lines()` filters on `v.language` alone, so the moment a row with
# `transcript_source='auto'` lands in `video`, `CorpusUpdater.catch_up` folds
# it into `subtitle` and a hand-written corpus quietly acquires a machine's
# words. The reader would have no way to tell, and there is no command to
# take a video back out.
#
# So the mapping is explicit and the default is `manual`: a build that wants
# machine captions has to say so by name.
BUILD_SOURCES: dict[str, tuple[str, ...]] = {
    "subtitle": ("manual",),
    "subtitle:llm": ("manual",),
    "subtitle:auto": ("auto",),
}

MANUAL: tuple[str, ...] = ("manual",)


def sources_for(build: str) -> tuple[str, ...]:
    """Which transcript sources `build` draws from.

    Unknown builds read hand-written subtitles, which is what every build
    that existed before this mapping did.
    """
    return BUILD_SOURCES.get(build, MANUAL)


class SubtitleSource:
    """Ordered access to `sentence` rows for one language.

    Rows are yielded per video in playback order, because that ordering is
    what makes the continuation lines reassemblable at all — a line ending
    mid-clause is continued by the next row of the same video.
    """

    def __init__(self, db, language: str = "de",
                 sources: tuple[str, ...] = MANUAL) -> None:
        self._db = db
        self._language = language
        self._sources = tuple(sources)

    def lines(self) -> list[RawLine]:
        rows = self._db.rows(
            """
            SELECT s.sentence_id, s.video_id, s.start_time, s.duration,
                   s.content, s.tokens
              FROM sentence s
              JOIN video v ON v.video_id = s.video_id
             WHERE v.language = %s
               AND v.transcript_source = ANY(%s)
             ORDER BY s.video_id, s.start_time, s.sentence_id
            """,
            (self._language, list(self._sources)),
        )
        return [
            RawLine(sentence_id=sid, video_id=vid, start_time=start,
                    duration=duration, content=content, tokens=tuple(tokens or ()))
            for sid, vid, start, duration, content, tokens in rows
        ]

    def videos(self) -> list[list[RawLine]]:
        """The same lines, partitioned per video."""
        return [
            list(group)
            for _, group in groupby(self.lines(), key=lambda line: line.video_id)
        ]
