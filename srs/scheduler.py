"""SM-2 scheduling.

Ported from language-app's `progression_service._update_srs`, which is the
part of that service worth borrowing — the surrounding rule table there is
wired to a chat and video app whose events do not exist here.

    correct    interval *= ease,  ease += 0.05 (capped),  repetitions += 1
    incorrect  interval  = 1,     ease -= 0.15 (floored), repetitions  = 0

An incorrect answer resets the interval but only nudges the ease, so a word
missed once comes back tomorrow without being permanently marked difficult.

Dates are jittered by a few per cent, intervals never (`_due`): cards
claimed in one go would otherwise come back in one go for as long as
they live.

Intervals are capped.  Growth is geometric, so a card answered correctly forty
times running reaches an interval that `timedelta` cannot represent, and the
review session crashes rather than scheduling it.  Ten years is already past
the point where a longer interval means anything.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from random import Random
from typing import TYPE_CHECKING

from srs.card import Card
from vocab.entry import Unit

if TYPE_CHECKING:
    from vocab.encounters import Rung


# A word marked known is a claim on probation (decided 2026-09-21). It counts
# as known at once -- the plan, the reel and the next step move on -- and a
# card is due the next day. Each passed review confirms it; at five it has
# graduated and is never asked again. Two failed reviews in a row un-mark
# it: the plan's decks assumed it was known, and it was not.
CONFIRMATIONS = 5
LAPSES_TO_UNMARK = 2

GRADUATED = "graduated"
UNMARKED = "unmarked"
SCHEDULED = "scheduled"


BY_DATE = "date"
BY_HEARING = "heard"


def due_now(cards: list[Card], now: datetime, heard: dict[Unit, "Rung"],
            enough: int) -> list[tuple[Card, str]]:
    """The cards to test now and the reason each: its date has come, or
    the word has climbed to rung `enough` of the hearing ladder since the
    card's last review (`vocab.encounters`) -- passive hearing never
    confirms a word, it calls the active test, once, when the word
    becomes familiar (decided 2026-09-22). Date first, then the called,
    soonest first."""
    def called(card: Card) -> bool:
        rung = heard.get(card.unit)
        if rung is None or rung.level < enough:
            return False
        # Since the last review, or since the claim: a word familiar
        # before it was marked known was heard before there was anything
        # to test, and the claim is due tomorrow, not now (`claimed`).
        since = card.last_review or card.due_date - timedelta(days=card.interval_days)
        return rung.counted_at > since
    out = [(card, BY_DATE) for card in cards if card.is_due(now)]
    early = [(card, BY_HEARING) for card in cards if not card.is_due(now) and called(card)]
    return out + sorted(early, key=lambda pair: pair[0].due_date)


def verdict(card: Card) -> str:
    """What a review just decided about the claim: `graduated`, `unmarked`
    or `scheduled` for another look."""
    if card.repetitions >= CONFIRMATIONS:
        return GRADUATED
    if card.lapses >= LAPSES_TO_UNMARK:
        return UNMARKED
    return SCHEDULED


class SM2Scheduler:
    DEFAULT_EASE = 2.5
    INITIAL_INTERVAL = 1.0
    EASE_BONUS = 0.05
    EASE_PENALTY = 0.15
    MAX_EASE = 3.0
    MIN_EASE = 1.3
    MAX_INTERVAL_DAYS = 3650.0
    # How far a due date may be nudged either way, and the interval
    # below which it is not nudged at all -- see `_due`.
    FUZZ = 0.05
    FUZZ_FLOOR = 2.5

    def new_card(self, unit: Unit, now: datetime) -> Card:
        """A card due immediately — a newly taught unit is reviewed the same day."""
        return Card(
            unit=unit,
            due_date=now,
            interval_days=self.INITIAL_INTERVAL,
            ease_factor=self.DEFAULT_EASE,
            repetitions=0,
        )

    def claimed(self, unit: Unit, now: datetime) -> Card:
        """The card for a word just marked known: due tomorrow, not now —
        the reader has the sentence in front of them this minute."""
        return replace(self.new_card(unit, now),
                       due_date=now + timedelta(days=self.INITIAL_INTERVAL))

    def _due(self, unit: Unit, interval: float, repetitions: int,
             now: datetime) -> datetime:
        """When a card at this interval comes back, nudged off the exact day.

        Claims made in one go are minted off one `now` -- 173 of them in
        one evening here -- and a shared interval times a shared ease
        keeps that batch whole for as long as it lives: everything learned
        together is asked together, for good. A few per cent either way
        breaks it up, and each review nudges again from where the last one
        left it, so the spread widens as the intervals do.

        The nudge is on the date and never on `interval_days`. The
        interval is what the next interval is computed from, so jitter
        there would compound into the schedule; and `vocab.encounters`
        lays the hearing ladder out by reading the intervals a perfect run
        of reviews gives, so a jittered interval would set the passive
        ladder drifting from the active schedule it is built to match.

        Drawn from the unit and the passes behind it rather than from
        chance, so the same history always schedules the same day: a card
        keeps its date when the page is loaded twice, and a test can say
        where it lands.

        Below `FUZZ_FLOOR` nothing is nudged. A day and a half of schedule
        spreads over hours, which buys nothing the review order does not
        already give -- and a missed card should come back tomorrow, not
        tomorrow give or take.
        """
        if interval < self.FUZZ_FLOOR:
            return now + timedelta(days=interval)
        spread = Random(f"{unit.kind}:{unit.key}:{repetitions}").uniform(
            -self.FUZZ, self.FUZZ)
        return now + timedelta(days=interval * (1 + spread))

    def review(self, card: Card, correct: bool, now: datetime) -> Card:
        if correct:
            interval = min(
                card.interval_days * card.ease_factor, self.MAX_INTERVAL_DAYS
            )
            ease = min(card.ease_factor + self.EASE_BONUS, self.MAX_EASE)
            repetitions = card.repetitions + 1
            lapses = 0
        else:
            interval = self.INITIAL_INTERVAL
            ease = max(card.ease_factor - self.EASE_PENALTY, self.MIN_EASE)
            repetitions = 0
            lapses = card.lapses + 1
        return replace(
            card,
            interval_days=interval,
            ease_factor=ease,
            repetitions=repetitions,
            lapses=lapses,
            due_date=self._due(card.unit, interval, repetitions, now),
            last_review=now,
        )
