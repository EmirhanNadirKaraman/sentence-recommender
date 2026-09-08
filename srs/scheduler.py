"""SM-2 scheduling.

Ported from language-app's `progression_service._update_srs`, which is the
part of that service worth borrowing — the surrounding rule table there is
wired to a chat and video app whose events do not exist here.

    correct    interval *= ease,  ease += 0.05 (capped),  repetitions += 1
    incorrect  interval  = 1,     ease -= 0.15 (floored), repetitions  = 0

An incorrect answer resets the interval but only nudges the ease, so a word
missed once comes back tomorrow without being permanently marked difficult.

Intervals are capped.  Growth is geometric, so a card answered correctly forty
times running reaches an interval that `timedelta` cannot represent, and the
review session crashes rather than scheduling it.  Ten years is already past
the point where a longer interval means anything.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from srs.card import Card
from vocab.entry import Unit


class SM2Scheduler:
    DEFAULT_EASE = 2.5
    INITIAL_INTERVAL = 1.0
    EASE_BONUS = 0.05
    EASE_PENALTY = 0.15
    MAX_EASE = 3.0
    MIN_EASE = 1.3
    MAX_INTERVAL_DAYS = 3650.0

    def new_card(self, unit: Unit, now: datetime) -> Card:
        """A card due immediately — a newly taught unit is reviewed the same day."""
        return Card(
            unit=unit,
            due_date=now,
            interval_days=self.INITIAL_INTERVAL,
            ease_factor=self.DEFAULT_EASE,
            repetitions=0,
        )

    def review(self, card: Card, correct: bool, now: datetime) -> Card:
        if correct:
            interval = min(
                card.interval_days * card.ease_factor, self.MAX_INTERVAL_DAYS
            )
            ease = min(card.ease_factor + self.EASE_BONUS, self.MAX_EASE)
            repetitions = card.repetitions + 1
        else:
            interval = self.INITIAL_INTERVAL
            ease = max(card.ease_factor - self.EASE_PENALTY, self.MIN_EASE)
            repetitions = 0
        return replace(
            card,
            interval_days=interval,
            ease_factor=ease,
            repetitions=repetitions,
            due_date=now + timedelta(days=interval),
            last_review=now,
        )
