"""Repairing subtitle lines with the local model.

Subtitle rows are not sentences: a third do not end in punctuation, many are
cut mid-clause, and the ASR leaves real errors behind.  `MergeCorrector`
rejoins and re-splits them but cannot fix anything inside the text.  This one
sends each stretch of lines to the model and takes back clean sentences.

Two things keep the model from being load-bearing:

  * it is asked which input lines each sentence came from, so provenance
    survives the rewrite and the original is always shown alongside;
  * any chunk whose reply does not parse, or comes back empty, falls through
    to `MergeCorrector` for that chunk alone.

Units are re-derived from the corrected text by `UnitAnalyzer` regardless of
which corrector ran, so a rewrite cannot desynchronise the roadmap from what
the learner reads.
"""
from __future__ import annotations

import json
import re

from corpus.corrector import MergeCorrector, SentenceCorrector
from corpus.sentence import RawLine, Sentence

SYSTEM = """\
You repair German subtitle lines into clean sentences.

The input is consecutive subtitle lines from one video, numbered. They are
split for display, not by sentence, so a sentence often spans several lines.

Your job:
- Join and split them into complete German sentences.
- Fix punctuation, capitalisation and obvious transcription errors.
- Drop stage directions, speaker labels and music markers.
- Change nothing else. Do not translate, summarise or invent content.
- If a sentence is left incomplete at the end of the input, leave it out.

Reply as JSON only:
{"sentences": [{"german": "...", "lines": [1, 2]}]}

"lines" lists the input line numbers the sentence came from.
"""


class LLMCorrector(SentenceCorrector):
    """Corrects a video's lines in chunks, falling back per chunk on failure."""

    def __init__(self, client, chunk_size: int = 25) -> None:
        self._client = client
        self._chunk_size = chunk_size
        self._fallback = MergeCorrector()
        self.chunks = 0
        self.fallbacks = 0

    @property
    def available(self) -> bool:
        return self._client.available

    def correct(self, lines: list[RawLine]) -> list[Sentence]:
        out: list[Sentence] = []
        for start in range(0, len(lines), self._chunk_size):
            chunk = lines[start:start + self._chunk_size]
            self.chunks += 1
            corrected = self._correct_chunk(chunk)
            if corrected is None:
                self.fallbacks += 1
                corrected = self._fallback.correct(chunk)
            out.extend(corrected)
        return out

    def _correct_chunk(self, chunk: list[RawLine]) -> list[Sentence] | None:
        numbered = "\n".join(
            f"{i}. {line.content.strip()}" for i, line in enumerate(chunk, start=1)
        )
        try:
            reply = self._client.complete(SYSTEM, numbered, temperature=0.2)
        except Exception:      # noqa: BLE001 — an unreachable model is not fatal
            return None
        parsed = self._parse(reply)
        if not parsed:
            return None
        return [self._build(chunk, german, numbers) for german, numbers in parsed]

    @staticmethod
    def _build(chunk: list[RawLine], german: str, numbers: list[int]) -> Sentence:
        """One corrected sentence, carrying the lines it was built from."""
        sources = [chunk[n - 1] for n in numbers if 1 <= n <= len(chunk)] or chunk
        return Sentence(
            text=german,
            raw_text=" ".join(line.content.strip() for line in sources),
            source_ids=tuple(line.sentence_id for line in sources),
        )

    @staticmethod
    def _parse(reply: str) -> list[tuple[str, list[int]]]:
        """Pull (german, lines) pairs out of the reply.

        Local models wrap JSON in prose or fences often enough that finding the
        first object is more reliable than trusting the whole response.
        """
        match = re.search(r"\{.*\}", reply, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return []
        out: list[tuple[str, list[int]]] = []
        for item in data.get("sentences", []):
            german = str(item.get("german", "")).strip()
            if not german:
                continue
            numbers = [n for n in item.get("lines", []) if isinstance(n, int)]
            out.append((german, numbers))
        return out
