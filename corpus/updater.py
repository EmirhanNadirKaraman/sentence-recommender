"""Bringing a cached subtitle build up to date without redoing it.

A full rebuild re-analyses every sentence in the corpus — about sixteen
milliseconds each, so thirty-five seconds for what is currently cached — when
a newly added video contributes maybe a hundred and fifty of them. Since a
video is either wholly in the cache or wholly absent, the ones already there
can simply be skipped.

Only subtitle builds work this way. Tatoeba arrives as one file with nothing
to add incrementally.
"""
from __future__ import annotations

from dataclasses import dataclass

from corpus.corrector import MergeCorrector
from corpus.source import SubtitleSource
from db import Database


@dataclass(frozen=True)
class Caught:
    """What the update added."""

    videos: int
    teachable: int
    context: int

    @property
    def anything(self) -> bool:
        return self.videos > 0


class CorpusUpdater:
    """Analyses the videos a build does not have yet, and appends them."""

    def __init__(self, app) -> None:
        self._app = app

    def catch_up(self, build: str = "subtitle") -> Caught:
        settings = self._app.settings
        have = self._app.corpus_store.video_ids(build)

        with Database(settings.database) as db:
            videos = SubtitleSource(db, settings.language).videos()
        fresh = [v for v in videos if v and v[0].video_id not in have]
        if not fresh:
            return Caught(0, 0, 0)

        # Imported here, not at module scope: `alignment` reads back from
        # `corpus`, and importing it while this package is still loading
        # leaves a half-built module behind.
        from alignment import SubtitleAligner   # noqa: PLC0415

        aligner, corrector = SubtitleAligner(), MergeCorrector()
        sentences = [s for video in fresh
                     for s in aligner.align(video, corrector.correct(video))]

        # A filter carries de-duplication state, so it has to see what is
        # already cached — otherwise a line repeated from an older video
        # sneaks in as new.
        sentence_filter = self._app.filter()
        sentence_filter.apply(self._app.corpus_store.load(build,
                                                          teachable_only=False))
        sentence_filter.rejected.clear()
        kept, dropped = sentence_filter.split(sentences)

        analysed = self._app.analyzer.analyze_all(kept)
        analysed += [s.as_context() for s in dropped]
        self._app.corpus_store.append(analysed, build)
        return Caught(len(fresh), len(kept), len(dropped))
