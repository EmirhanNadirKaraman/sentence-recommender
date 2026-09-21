"""Analysing a corpus on every core.

`UnitAnalyzer.analyze_all` parses on worker processes and reads the units
off the parsed docs in the parent — spaCy's own `n_process`, which pickles
every Doc back to the one process that then does the second half of the
work alone. Measured on 2026-09-21: 596 sentences a second to parse per
process, 1,455 a second to read the units off them, and the subtitle
build's four workers sat at 30–47% of a core each behind a parent at 70%
— two cores of eight busy, and seven to fifteen minutes for 262,000
sentences.

Here a worker does both halves for a chunk of sentences and hands back
only what the second pass needs: each sentence's units and surfaces, and
the evidence the corpus-wide vote reads. No Doc crosses a process. The
analyser is unchanged and this file is not in the fingerprint, on purpose:
it decides nothing about what a sentence yields, only on how many cores.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Callable

from corpus.analyzer import Evidence, UnitAnalyzer
from corpus.sentence import Sentence

# Sentences a worker takes at a time. Large enough that the pool's overhead
# is nothing, small enough that eight workers never wait on a last chunk.
CHUNK = 2_000

_WORKER: UnitAnalyzer | None = None


def _start(patterns: frozenset[str], language: str) -> None:
    """Once per worker: the analyser, with spaCy and its tables loaded."""
    global _WORKER
    _WORKER = UnitAnalyzer(patterns, language)
    _WORKER.verb_lemmas


def _read(texts: list[str]) -> tuple[list, Evidence]:
    evidence = Evidence()
    found = [_WORKER._units(doc, evidence)
             for doc in _WORKER.matcher.nlp.pipe(texts, batch_size=256)]
    return found, evidence


def _absorb(into: Evidence, part: Evidence) -> None:
    into.names.update(part.names)
    into.content.update(part.content)
    for surface, lemmas in part.by_surface.items():
        into.by_surface[surface].update(lemmas)
    into.prefixed |= part.prefixed


def analyze_all(analyzer: UnitAnalyzer, sentences: list[Sentence], processes: int,
                on_progress: Callable[[int, int], None] | None = None) -> list[Sentence]:
    """`UnitAnalyzer.analyze_all`, over `processes` workers.

    The same answer: the first pass is per sentence and the second reads a
    tally, so the tally is merged and the second pass runs once, here. A
    small corpus, or one process, takes the analyser's own path — the pool
    costs a few seconds to start and is not worth it under a chunk.
    """
    if processes <= 1 or len(sentences) <= CHUNK:
        return analyzer.analyze_all(sentences)
    texts = [s.text for s in sentences]
    chunks = [texts[i:i + CHUNK] for i in range(0, len(texts), CHUNK)]
    evidence = Evidence()
    analysed: list[Sentence] = []
    with ProcessPoolExecutor(
            max_workers=processes, initializer=_start,
            initargs=(analyzer._patterns, analyzer._language)) as pool:
        for found, part in pool.map(_read, chunks):
            start = len(analysed)
            analysed.extend(s.with_units(units, surfaces)
                            for s, (units, surfaces)
                            in zip(sentences[start:start + len(found)], found))
            _absorb(evidence, part)
            if on_progress:
                on_progress(len(analysed), len(sentences))
    corrections = analyzer._lemma_corrections(evidence)
    return analyzer._normalise(
        analysed,
        analyzer._proper_nouns(evidence),
        {**corrections, **analyzer._prefixed_corrections(evidence, corrections)},
    )
