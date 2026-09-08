"""Reads raw subtitle rows out of the shared database, grouped by video."""
from __future__ import annotations

from itertools import groupby

from corpus.sentence import RawLine


class SubtitleSource:
    """Ordered access to `sentence` rows for one language.

    Rows are yielded per video in playback order, because that ordering is
    what makes the continuation lines reassemblable at all — a line ending
    mid-clause is continued by the next row of the same video.
    """

    def __init__(self, db, language: str = "de") -> None:
        self._db = db
        self._language = language

    def lines(self) -> list[RawLine]:
        rows = self._db.rows(
            """
            SELECT s.sentence_id, s.video_id, s.start_time, s.duration,
                   s.content, s.tokens
              FROM sentence s
              JOIN video v ON v.video_id = s.video_id
             WHERE v.language = %s
             ORDER BY s.video_id, s.start_time, s.sentence_id
            """,
            (self._language,),
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
