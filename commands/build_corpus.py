"""`build-corpus` — assemble, filter, analyse and cache one source.

The expensive command.  Analysis runs the German parser plus the phrase
matcher over every sentence, so the result is cached under a build name and
the other commands never repeat it.

Build names carry how the sentences were made, not just where they came from,
because the same source corrected two different ways gives two different
corpora and neither should overwrite the other.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from alignment import SubtitleAligner
from corpus import (
    LLMCorrector, MergeCorrector, SubtitleSource, sources_for,
)
from db import Database
from generation import LLMClient


def correct_one(lines):
    """One video, corrected and timed — the unit of parallel work.

    Module level so a worker process can find it, and it builds its own
    corrector and aligner because both are stateless: `MergeCorrector` keeps
    nothing between calls and `SubtitleAligner` has no `__init__` at all.
    `LLMCorrector` is a different matter — it counts chunks, fallbacks and
    rejections on itself — which is why only the merge path comes here.
    """
    return SubtitleAligner().align(lines, MergeCorrector().correct(lines))


def default_workers() -> int:
    """One per core less the parent, capped at six.

    Capped because each worker is a fork of a parent already holding the
    whole subtitle corpus, and this machine has been driven into the swapper
    by less. `--workers 1` turns the pool off.
    """
    return max(1, min(6, (os.cpu_count() or 2) - 1))


class BuildCorpusCommand:
    """Builds one named corpus.

      subtitle       the language-app subtitle corpus, rejoined and re-split
      subtitle:llm   the same lines repaired by the local model
      subtitle:auto  the same treatment, over the videos whose captions a
                     machine wrote — a separate build because it is separate
                     material, not a better reading of the same material
    """

    def run(self, app, source: str, limit: int | None = None,
            corrector: str = "merge", min_words: int | None = None,
            path: str | None = None, workers: int | None = None) -> None:
        settings = app.settings
        started = time.time()
        build = f"{source}:llm" if source == "subtitle" and corrector == "llm" else source
        timed = source.startswith("subtitle")

        sentences = self._collect(app, source, corrector, path, workers)
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
        if timed and dropped:
            analysed = analysed + [s.as_context() for s in dropped]
            print(f"  keeping {len(dropped)} more for the overlay only")

        app.corpus_store.save(analysed, build=build)
        units = len({u for s in analysed for u in s.units})
        print(f"  cached {len(analysed)} sentences, {units} distinct units "
              f"({time.time() - started:.0f}s total)")

    def _collect(self, app, source: str, corrector: str,
                 path: str | None = None, workers: int | None = None):
        settings = app.settings
        if source == "transcript":
            return self._transcripts(path)
        if source not in ("subtitle", "subtitle:auto"):
            raise SystemExit(
                f"unknown source {source!r} (expected subtitle, subtitle:auto "
                "or transcript)")

        # Who wrote the captions this build is made of. Without it both
        # subtitle builds read every video and `subtitle` would hold the
        # machine's words as well as the hand-written ones, with nothing in
        # the corpus saying which was which.
        with Database(settings.own) as db:
            videos = SubtitleSource(db, settings.language,
                                    sources_for(source)).videos()
        engine = self._corrector(corrector, settings)
        aligner = SubtitleAligner()
        print(f"  {len(videos)} videos, correcting with {corrector}…", flush=True)

        # Aligned per video: a sentence's timing comes from the rows of its own
        # video, and the aligner needs both sides of one video to match them.
        # Correction is pure Python with no model and no network, and each
        # video is independent, so the merge path spreads it over processes.
        # `executor.map` yields in the order it was given, which is the whole
        # of what reproducibility needs here: the filter's duplicate check
        # carries state along the list, so a different order would change
        # which of two identical lines survives.
        pool = default_workers() if workers is None else workers
        if corrector == "merge" and pool > 1 and len(videos) > 1:
            print(f"  correcting on {pool} processes…", flush=True)
            with ProcessPoolExecutor(max_workers=pool) as run:
                done = list(run.map(correct_one, videos, chunksize=8))
            sentences = [s for video in done for s in video]
        else:
            sentences = []
            for index, video in enumerate(videos, start=1):
                sentences.extend(aligner.align(video, engine.correct(video)))
                if corrector == "llm":
                    print(f"    video {index}/{len(videos)} — "
                          f"{len(sentences)} sentences", flush=True)
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
