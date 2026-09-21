"""One scheduled review item."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from vocab.entry import Unit


@dataclass(frozen=True)
class Card:
    """SM-2 state for a single unit.

    Immutable: the scheduler returns a new card rather than mutating this one,
    so a review can be computed and inspected before anything is stored.

    Unlike the app this borrows from, there is one card per unit rather than a
    passive and an active card per unit.  Both kinds of unit are reviewed by
    production here — a word by cloze, a pattern by writing a sentence — so a
    second direction would have nothing different to ask.
    """

    unit: Unit
    due_date: datetime
    interval_days: float = 1.0
    ease_factor: float = 2.5
    repetitions: int = 0
    last_review: datetime | None = None
    card_id: int | None = None
    # Failed reviews in a row. `repetitions` is passes in a row; between
    # them a card says how the claim is going -- see `srs.scheduler.verdict`.
    lapses: int = 0

    def is_due(self, now: datetime) -> bool:
        return self.due_date <= now

    def with_id(self, card_id: int) -> "Card":
        return replace(self, card_id=card_id)
