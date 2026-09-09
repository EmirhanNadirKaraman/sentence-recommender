"""`difficulty` — how hard each video is, and what it would teach.

Two numbers, not one. A single score cannot tell the two useless cases apart:
a video you already understand completely teaches nothing, and one you
understand none of teaches nothing either, and both would score badly on any
scalar that means "hard".

  comprehension  the share of its sentences with no unknown unit at all.
                 Below roughly 95% listening stops being acquisition and
                 becomes decoding.
  yield          how many sentences are i+1, and how many study-list goals
                 it would unblock — what watching it actually buys.

Read off the cached corpus, so it costs a load and no analysis.
"""
from __future__ import annotations

from collections import defaultdict

from db import Database

from watchability import (COMFORTABLE, ENOUGH_LINES, IDEAL_MINUTES,
                          LONG_MINUTES, SHORT_MINUTES, watchability)


class DifficultyCommand:
    """Scores every video already in the corpus."""

    def run(self, app, source: str = "subtitle", limit: int = 30,
            sort: str = "yield") -> None:
        known = app.known_set().units
        goals = frozenset(app.goal_units)
        minutes = self._durations(app)
        by_video = defaultdict(list)
        for sentence in app.corpus(source, list_only=False):
            if sentence.timing:
                by_video[sentence.timing.video_id].append(sentence)
        if not by_video:
            raise SystemExit(f"no timed sentences in {source!r}")

        rows = [self._score(vid, group, known, goals, minutes.get(vid))
                for vid, group in by_video.items()]
        rows.sort(key=lambda r: -r[sort])
        print(f"\n  {len(rows)} videos, best-first by {sort}\n")
        print(f"  {'video':13} {'mins':>5} {'lines':>6} {'known':>7} {'i+1':>6} "
              f"{'teaches':>8} {'watch':>6}")
        for row in rows[:limit]:
            length = f"{row['minutes']:.0f}" if row["minutes"] else "—"
            print(f"  {row['video']:13} {length:>5} {row['lines']:>6,} "
                  f"{row['comprehension']:>6.0%} {row['i+1']:>6,} "
                  f"{row['yield']:>8,} {row['watch']:>6.2f}")
        print(f"\n  comprehension = sentences you can already read"
              f"\n  teaches       = study-list goals that are the only new thing"
              f" in some sentence here")

    @staticmethod
    def _durations(app) -> dict[str, float]:
        with Database(app.settings.database) as db:
            rows = db.rows("SELECT video_id, duration FROM video"
                           " WHERE duration IS NOT NULL")
        return {video: seconds / 60 for video, seconds in rows}

    @staticmethod
    def _score(video: str, sentences: list, known, goals,
               minutes: float | None) -> dict:
        readable = teachable = 0
        unknown_units: set = set()
        unblocks: set = set()
        for sentence in sentences:
            missing = sentence.units - known
            unknown_units |= missing
            if not missing:
                readable += 1
            elif len(missing) == 1:
                teachable += 1
                unblocks |= missing & goals
        comprehension = readable / len(sentences)
        return {
            "video": video,
            "lines": len(sentences),
            "minutes": minutes,
            "watch": watchability(comprehension, minutes,
                                                     len(sentences)),
            "comprehension": comprehension,
            "i+1": teachable,
            "yield": len(unblocks),
            "unknown": len(unknown_units),
        }
