"""Turning subtitle rows into sentences.

Two implementations behind one interface:

  MergeCorrector  rule-based.  Joins consecutive lines and splits on sentence
                  boundaries.  No dependencies, runs in milliseconds, and is
                  the fallback whenever the LLM is unavailable or its output
                  fails validation.

  LLMCorrector    sends each video's lines to a local model and takes back
                  corrected sentences (see corpus/llm.py).

Both produce `Sentence` objects carrying the original text alongside the
corrected one, so nothing the corrector does is invisible.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

from corpus.sentence import RawLine, Sentence

# Stage directions and typography the subtitle authors added, never spoken:
#   "*** Es ist so weit."   "*Olaf lacht.* Ach, hier sind sie ja,"
STAGE_DIRECTION = re.compile(r"\*[^*]*\*|\*+|\[[^\]]*\]|♪")
WHITESPACE = re.compile(r"\s+")

# A boundary is terminal punctuation followed by the start of something new.
# Deliberately conservative: German abbreviations ("z.B.") are lower-case
# after the dot, so requiring a capital or an opening quote skips them.
BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[„"»\'A-ZÄÖÜ])')


class SentenceCorrector(ABC):
    """Assembles one video's subtitle lines into sentences."""

    @abstractmethod
    def correct(self, lines: list[RawLine]) -> list[Sentence]:
        ...


class MergeCorrector(SentenceCorrector):
    """Rule-based assembly — no model, no network."""

    def correct(self, lines: list[RawLine]) -> list[Sentence]:
        joined, spans = self._join(lines)
        out: list[Sentence] = []
        for start, end in self._boundaries(joined):
            text = joined[start:end].strip()
            if not text:
                continue
            ids = tuple(sid for lo, hi, sid in spans if lo < end and hi > start)
            raw = " ".join(
                line.content.strip() for line in lines if line.sentence_id in ids
            )
            out.append(Sentence(text=text, raw_text=raw, source_ids=ids))
        return out

    @staticmethod
    def _join(lines: list[RawLine]) -> tuple[str, list[tuple[int, int, int]]]:
        """Concatenate cleaned line text, remembering which rows cover which chars."""
        parts: list[str] = []
        spans: list[tuple[int, int, int]] = []
        cursor = 0
        for line in lines:
            text = WHITESPACE.sub(" ", STAGE_DIRECTION.sub(" ", line.content)).strip()
            if not text:
                continue
            if parts:
                parts.append(" ")
                cursor += 1
            parts.append(text)
            spans.append((cursor, cursor + len(text), line.sentence_id))
            cursor += len(text)
        return "".join(parts), spans

    @staticmethod
    def _boundaries(text: str) -> list[tuple[int, int]]:
        cuts = [0, *(m.end() for m in BOUNDARY.finditer(text)), len(text)]
        return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]
