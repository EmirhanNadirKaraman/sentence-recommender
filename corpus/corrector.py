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
# The usual "capital letter after the dot" test does not work in German, where
# every noun is capitalised — "Ich mag z.B. Kaffee" would split at the
# abbreviation.  So a candidate boundary is also checked against the token that
# ends at it.
BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[„"»\'A-ZÄÖÜ])')

# Abbreviations that end in a period without ending a sentence.  Single and
# double letters ("z.B.", "u.a.") are caught by the length rule instead.
ABBREVIATIONS = frozenset({
    "bzw", "ca", "evtl", "ggf", "inkl", "max", "min", "usw", "vgl",
    "Abb", "Dr", "Fr", "Hr", "Nr", "Prof", "St",
})


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

    @classmethod
    def _boundaries(cls, text: str) -> list[tuple[int, int]]:
        cuts = [0]
        cuts.extend(
            match.end() for match in BOUNDARY.finditer(text)
            if not cls._is_abbreviation(text[:match.start()])
        )
        cuts.append(len(text))
        return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]

    @staticmethod
    def _is_abbreviation(prefix: str) -> bool:
        """Does `prefix` end in an abbreviation rather than a sentence?

        Looks at the whitespace-delimited token the punctuation belongs to:
        "z.B." carries an internal period, "Dr." is on the list, and anything
        one or two letters long ("u.", "a.") is not a word.
        """
        token = prefix.split()[-1].rstrip(".!?") if prefix.split() else ""
        if not token:
            return False
        if "." in token:
            return True
        return token in ABBREVIATIONS or len(token) <= 2
