"""The terminal review loop."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from srs.prompt import ReviewPrompt
from vocab.entry import Unit


@dataclass
class SessionReport:
    reviewed: int = 0
    correct: int = 0
    skipped: int = 0
    missed: list[Unit] = field(default_factory=list)

    def summary(self) -> str:
        if not self.reviewed:
            return "Nothing was reviewed."
        rate = 100 * self.correct / self.reviewed
        return (f"{self.reviewed} reviewed · {self.correct} correct "
                f"({rate:.0f}%) · {self.skipped} skipped")


class ReviewSession:
    """Presents due cards and records the answers.

    Input and output are injected so the loop can be driven by a test as
    easily as by a person.
    """

    def __init__(self, store, scheduler, prompts, read=input, write=print) -> None:
        self._store = store
        self._scheduler = scheduler
        self._prompts = prompts
        self._read = read
        self._write = write

    def run(self, known: frozenset[Unit], limit: int = 20,
            now: datetime | None = None) -> SessionReport:
        now = now or datetime.now()
        report = SessionReport()
        for card in self._store.due(now, limit):
            outcome = self._review(self._prompts.build(card, known))
            if outcome is None:
                report.skipped += 1
                continue
            report.reviewed += 1
            report.correct += int(outcome)
            if not outcome:
                report.missed.append(card.unit)
            self._store.save(self._scheduler.review(card, outcome, now))
        return report

    def _review(self, prompt: ReviewPrompt) -> bool | None:
        """True or False once graded, None if skipped."""
        self._write(f"\n{prompt.heading}\n")
        for line in prompt.question_lines():
            self._write(line)

        answer = self._read("\n> ").strip()
        if answer in {"", "skip"}:
            return None

        if prompt.self_graded:
            self._write("\n   how it is actually said:")
            for line in prompt.answer_lines():
                self._write(line)
            return self._read("\nDid you get it right? [y/N] ").strip().lower() == "y"

        correct = self._normalise(answer) == self._normalise(prompt.answer)
        self._write("   ✓ correct" if correct else f"   ✗ {prompt.answer}")
        return correct

    @staticmethod
    def _normalise(text: str) -> str:
        return unicodedata.normalize("NFC", text.strip()).lower()
