"""Which assembled sentences are worth teaching.

Applied after correction, before unit analysis.  Every rejection is counted so
`build` can report what the corpus actually cost — a silent filter that halves
the pool is worse than no filter.
"""
from __future__ import annotations

import re
from collections import Counter

from corpus.sentence import Sentence
from vocab.loader import normalize

LEFTOVER_ARTIFACT = re.compile(r"[\[\]<>_♪*…]|--|\.\.\.")
ALPHANUMERIC = re.compile(r"\W+", re.UNICODE)


class SentenceFilter:
    """Rejects fragments, artifacts, and repeats.

    `min_tokens`/`max_tokens` bound difficulty at both ends: below the floor a
    sentence carries too little context to learn from, above the ceiling a
    single unknown word is not really what makes it hard.
    """

    def __init__(self, min_tokens: int = 4, max_tokens: int = 25) -> None:
        self._min = min_tokens
        self._max = max_tokens
        self.rejected: Counter[str] = Counter()
        self._seen: set[str] = set()

    def keep(self, sentence: Sentence) -> bool:
        reason = self._reject_reason(sentence)
        if reason:
            self.rejected[reason] += 1
            return False
        self._seen.add(self._fingerprint(sentence.text))
        return True

    def apply(self, sentences: list[Sentence]) -> list[Sentence]:
        return [s for s in sentences if self.keep(s)]

    def _reject_reason(self, sentence: Sentence) -> str | None:
        text = sentence.text.strip()
        if not text:
            return "empty"
        if LEFTOVER_ARTIFACT.search(text):
            return "artifact"
        if not text.endswith((".", "!", "?")):
            return "unterminated"
        words = text.split()
        if not (self._min <= len(words) <= self._max):
            return "length"
        if self._fingerprint(text) in self._seen:
            return "duplicate"
        return None

    @staticmethod
    def _fingerprint(text: str) -> str:
        return ALPHANUMERIC.sub("", normalize(text))
