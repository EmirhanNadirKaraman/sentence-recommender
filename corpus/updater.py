"""Bringing a cached subtitle build up to date without redoing it.

A full rebuild re-analyses every sentence in the corpus — about sixteen
milliseconds each, so thirty-five seconds for what is currently cached — when
a newly added video contributes maybe a hundred and fifty of them. Since a
video is either wholly in the cache or wholly absent, the ones already there
can simply be skipped.

Only subtitle builds work this way, which is now the only kind there is.
"""
from __future__ import annotations

from dataclasses import dataclass

from corpus.corrector import MergeCorrector
from corpus.source import SubtitleSource
from db import Database


@dataclass(frozen=True)
class Caught:
    """What the update added, or why it would not."""

    videos: int
    teachable: int
    context: int
    refused: str = ""
    """The fingerprint the build was made with, when appending was refused."""

    @property
    def anything(self) -> bool:
        return self.videos > 0

    def report(self) -> str:
        """One line for a person, whichever of the two happened."""
        if self.refused:
            return ("not analysed — this build was made by different rules "
                    f"(fingerprint {self.refused}), so new sentences cannot "
                    "be appended beside the old ones; rebuild it with "
                    "`python main.py build-corpus subtitle`")
        return (f"{self.teachable} sentences to study from, "
                f"{self.context} more for the overlay")


class CorpusUpdater:
    """Analyses the videos a build does not have yet, and appends them."""

    def __init__(self, app) -> None:
        self._app = app

    def catch_up(self, build: str = "subtitle") -> Caught:
        settings = self._app.settings
        store = self._app.corpus_store

        # Appending is only safe under the rules the build was made with. The
        # stored units and the ones about to go beside them have to mean the
        # same thing: `keep` and `well_formed` and the phrase matcher all
        # decide what a unit *is*, and a corpus whose halves disagree about
        # that has no marker saying where one half ends. A full rebuild is the
        # only fix, so this says so rather than quietly making the mess.
        #
        # Only the analyser fingerprint blocks. `parser_changed` — a different
        # spaCy than the one that built it — is deliberately a warning here as
        # it is everywhere else in this file's neighbours: it is environment
        # drift rather than a decision, and a patch release of the parser
        # should not silently stop every import from being analysed at all.
        made_with = store.stale().get(build)
        if made_with:
            return Caught(0, 0, 0, refused=made_with)

        have = store.video_ids(build)

        with Database(settings.own) as db:
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
        sentence_filter.apply(store.load(build,
                                                          teachable_only=False))
        sentence_filter.rejected.clear()
        kept, dropped = sentence_filter.split(sentences)

        analysed = self._app.analyzer.analyze_all(kept)
        analysed += [s.as_context() for s in dropped]
        store.append(analysed, build)
        return Caught(len(fresh), len(kept), len(dropped))
