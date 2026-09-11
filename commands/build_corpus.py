"""`build-corpus` — assemble, filter, analyse and cache one source.

The expensive command.  Analysis runs the German parser plus the phrase
matcher over every sentence, so the result is cached under a build name and
the other commands never repeat it.

Build names carry how the sentences were made, not just where they came from,
because the same source corrected two different ways gives two different
corpora and neither should overwrite the other.
"""
from __future__ import annotations

import time
from pathlib import Path

from alignment import SubtitleAligner
from corpus import (
    LLMCorrector, MergeCorrector, SubtitleSource,
)
from db import Database
from generation import LLMClient


class BuildCorpusCommand:
    """Builds one named corpus.

      subtitle       the language-app subtitle corpus, rejoined and re-split
      subtitle:llm   the same lines repaired by the local model
    """

    def run(self, app, source: str, limit: int | None = None,
            corrector: str = "merge", min_words: int | None = None,
            path: str | None = None) -> None:
        settings = app.settings
        started = time.time()
        build = f"{source}:llm" if source == "subtitle" and corrector == "llm" else source

        sentences = self._collect(app, source, corrector, path)
        print(f"{build}: {len(sentences)} sentences from source "
              f"({time.time() - started:.0f}s)")

        sentence_filter = app.filter(min_words)
        kept, dropped = sentence_filter.split(sentences)
        print(f"  filtered to {len(kept)}  (rejected {dict(sentence_filter.rejected)})")
        if limit:
            kept = kept[:limit]
            print(f"  limited to {len(kept)}")

        print(f"  analysing with {settings.analysis_processes} processes…", flush=True)
        analysed = app.analyzer.analyze_all(kept)

        # Subtitle builds keep what the filter set aside, unanalysed. Those
        # sentences are not worth studying from, but they were still said, and
        # an overlay assembled only from the survivors has holes in it.
        if source == "subtitle" and dropped:
            analysed = analysed + [s.as_context() for s in dropped]
            print(f"  keeping {len(dropped)} more for the overlay only")

        app.corpus_store.save(analysed, build=build)
        units = len({u for s in analysed for u in s.units})
        print(f"  cached {len(analysed)} sentences, {units} distinct units "
              f"({time.time() - started:.0f}s total)")

    def _collect(self, app, source: str, corrector: str, path: str | None = None):
        settings = app.settings
        if source == "transcript":
            return self._transcripts(path)
        if source != "subtitle":
            raise SystemExit(
                f"unknown source {source!r} (expected subtitle or transcript)")

        with Database(settings.own) as db:
            videos = SubtitleSource(db, settings.language).videos()
        engine = self._corrector(corrector, settings)
        aligner = SubtitleAligner()
        print(f"  {len(videos)} videos, correcting with {corrector}…", flush=True)

        # Aligned per video: a sentence's timing comes from the rows of its own
        # video, and the aligner needs both sides of one video to match them.
        sentences = []
        for index, video in enumerate(videos, start=1):
            sentences.extend(aligner.align(video, engine.correct(video)))
            if corrector == "llm":
                print(f"    video {index}/{len(videos)} — {len(sentences)} sentences",
                      flush=True)
        if isinstance(engine, LLMCorrector) and engine.fallbacks:
            detail = (f", {engine.rejected} of them for losing the original wording"
                      if engine.rejected else "")
            print(f"  {engine.fallbacks} of {engine.chunks} chunks fell back "
                  f"to the rule-based corrector{detail}")
        return sentences

    @staticmethod
    def _transcripts(path: str | None):
        """Written transcripts, which need neither aligner nor corrector.

        Both of those exist to undo what subtitling does to a sentence — cut
        it at a line width and stamp the pieces with times. A transcript is
        already prose: it is wrapped, and its punctuation says where the
        sentences end.
        """
        from corpus.transcripts import TranscriptSource   # noqa: PLC0415

        root = Path(path or "Easy German Transcripts")
        if not root.exists():
            raise SystemExit(f"no transcripts at {root}")
        source = TranscriptSource(root)
        files = source.files()
        print(f"  {len(files)} transcript files under {root}…", flush=True)
        sentences = source.sentences()
        withtr = sum(1 for s in sentences if s.translation)
        print(f"  {len(sentences):,} sentences, {withtr:,} with a translation")
        return sentences

    @staticmethod
    def _corrector(name: str, settings):
        if name == "merge":
            return MergeCorrector()
        if name != "llm":
            raise SystemExit(f"unknown corrector {name!r} (expected merge or llm)")
        client = LLMClient(timeout=settings.llm_timeout)
        if not client.available:
            raise SystemExit(
                "no local model configured — set LLM_BASE_URL and LLM_MODEL in .env"
            )
        return LLMCorrector(client, settings.llm_chunk_size)
