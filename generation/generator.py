"""Synthesising an i+1 sentence when the corpus has none.

Used only as a fallback: some words in the roadmap appear in no sentence that
is i+1 against the learner's vocabulary at that moment, and a card with no
readable example is not much of a card.

The model cannot be trusted to honour the constraint — asked for a sentence
using only known words it will reach for others anyway — so generation is a
loop, not a call.  Every candidate is re-analysed with the *same* analyser the
corpus was built with, and accepted only when its unknowns are exactly the
target.  Rejected words are named back to the model on the next attempt.
"""
from __future__ import annotations

import json
import re

from corpus.sentence import GENERATED, Sentence
from vocab.entry import Unit

SYSTEM = """\
You write single German example sentences for a language learner.

Rules:
- Write exactly ONE German sentence.
- It must use the target word or pattern naturally.
- Every OTHER word must come from the learner's known vocabulary below.
- Keep it short and concrete: 5 to 12 words.
- Reply as JSON: {"german": "...", "english": "..."}
"""

USER = """\
Target: {target}

Known vocabulary:
{vocabulary}
"""

RETRY = """\
That sentence used words the learner does not know: {offenders}.
Write a different sentence for "{target}" without those words.
"""


class SentenceGenerator:
    """Generates and verifies one sentence per call."""

    def __init__(self, client, analyzer, max_attempts: int = 4) -> None:
        self._client = client
        self._analyzer = analyzer
        self.max_attempts = max_attempts
        self.attempts = 0
        self.accepted = 0

    @property
    def available(self) -> bool:
        return self._client.available

    def generate(
        self,
        target: Unit,
        known: frozenset[Unit],
        vocabulary: list[str],
    ) -> Sentence | None:
        """A verified i+1 sentence for `target`, or None if the model
        never produced one within `max_attempts`."""
        prompt = USER.format(target=target.key, vocabulary=", ".join(vocabulary))
        for _ in range(self.max_attempts):
            self.attempts += 1
            candidate = self._ask(prompt)
            if candidate is None:
                continue
            analysed = self._analyzer.analyze_all([candidate])[0]
            offenders = analysed.units - known - {target}
            if not offenders and target in analysed.units:
                self.accepted += 1
                return analysed
            prompt = RETRY.format(
                target=target.key,
                offenders=", ".join(sorted(u.key for u in offenders)) or "(target missing)",
            )
        return None

    def _ask(self, prompt: str) -> Sentence | None:
        try:
            reply = self._client.complete(SYSTEM, prompt)
        except Exception:      # noqa: BLE001 — a dead model must not stop a review
            return None
        parsed = self._parse(reply)
        if parsed is None:
            return None
        german, english = parsed
        return Sentence(text=german, origin=GENERATED, translation=english)

    @staticmethod
    def _parse(reply: str) -> tuple[str, str] | None:
        """Pull {german, english} out of the reply.

        Local models wrap JSON in prose or fences often enough that finding the
        first object is more reliable than trusting the whole response.
        """
        match = re.search(r"\{.*\}", reply, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return None
        german = str(data.get("german", "")).strip()
        english = str(data.get("english", "")).strip()
        return (german, english) if german else None
