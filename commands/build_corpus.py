"""`build-corpus` — assemble, filter, analyse and cache one source.

The expensive command.  Analysis runs the German parser plus the phrase
matcher over every sentence, so the result is cached under a build name and
the other commands never repeat it.
"""
from __future__ import annotations

import time

from corpus import (
    MergeCorrector, SubtitleSource, TatoebaSource,
)
from db import Database


class BuildCorpusCommand:
    """Builds one named corpus.

      tatoeba   276k human-written German sentences with English translations
      subtitle  the language-app subtitle corpus, reassembled into sentences
    """

    def run(self, app, source: str, limit: int | None = None) -> None:
        settings = app.settings
        started = time.time()

        sentences = self._collect(app, source)
        print(f"{source}: {len(sentences)} sentences from source "
              f"({time.time() - started:.0f}s)")

        sentence_filter = app.filter()
        kept = sentence_filter.apply(sentences)
        print(f"  filtered to {len(kept)}  (rejected {dict(sentence_filter.rejected)})")
        if limit:
            kept = kept[:limit]
            print(f"  limited to {len(kept)}")

        print(f"  analysing with {settings.analysis_processes} processes…", flush=True)
        analysed = app.analyzer.analyze_all(kept)

        app.corpus_store.save(analysed, build=source)
        units = len({u for s in analysed for u in s.units})
        print(f"  cached {len(analysed)} sentences, {units} distinct units "
              f"({time.time() - started:.0f}s total)")

    @staticmethod
    def _collect(app, source: str):
        settings = app.settings
        if source == "tatoeba":
            return TatoebaSource(
                settings.tatoeba_sentences, settings.tatoeba_links
            ).sentences()
        if source == "subtitle":
            with Database(settings.database) as db:
                videos = SubtitleSource(db, settings.language).videos()
            corrector = MergeCorrector()
            return [s for video in videos for s in corrector.correct(video)]
        raise SystemExit(f"unknown source {source!r} (expected tatoeba or subtitle)")
