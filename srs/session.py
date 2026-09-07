"""The terminal review loop."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from srs.card import Card
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
            return "Nothing was due."
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
        """True/False for graded, None for skipped."""
        self._write(f"\n{prompt.heading}\n")
        for line, example in zip(prompt.cloze or ("",) * len(prompt.examples),
                                 prompt.examples):
            if line:
                self._write(f"   {line}")
            if example.translation:
                self._write(f"     {example.translation}")
        if not prompt.examples:
            self._write("   (no example sentences available)")

        answer = self._read("\n> ").strip()
        if answer in {"", "skip"}:
            return None

        if prompt.self_graded:
            for example in prompt.examples:
                self._write(f"   e.g. {example.text}")
            return self._read("Did you get it right? [y/N] ").strip().lower() == "y"

        correct = self._normalise(answer) == self._normalise(prompt.answer)
        self._write("   ✓ correct" if correct else f"   ✗ {prompt.answer}")
        return correct

    @staticmethod
    def _normalise(text: str) -> str:
        return unicodedata.normalize("NFC", text.strip()).lower()
