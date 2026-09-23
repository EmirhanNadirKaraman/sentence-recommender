"""SM-2 scheduling, card presentation, and the review loop."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from corpus.sentence import Sentence
from roadmap import ExampleIndex
from srs import Card, PromptBuilder, ReviewSession, SM2Scheduler
from vocab.entry import Unit

NOW = datetime(2026, 1, 1, 12, 0)


def sentence(text: str, unit: Unit, surface: str, translation: str | None = None,
             extra: set[Unit] = frozenset()) -> Sentence:
    return Sentence(text=text, translation=translation).with_units(
        frozenset({unit}) | frozenset(extra), ((unit, surface),)
    )


class SM2SchedulerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scheduler = SM2Scheduler()

    def test_new_card_is_due_immediately(self) -> None:
        card = self.scheduler.new_card(Unit.lemma("haus"), NOW)
        self.assertTrue(card.is_due(NOW))
        self.assertEqual(card.repetitions, 0)

    def test_correct_answers_stretch_the_interval(self) -> None:
        card = self.scheduler.new_card(Unit.lemma("haus"), NOW)
        first = self.scheduler.review(card, correct=True, now=NOW)
        second = self.scheduler.review(first, correct=True, now=NOW)
        self.assertAlmostEqual(first.interval_days, 2.5)
        self.assertAlmostEqual(second.interval_days, 2.5 * 2.55)
        self.assertEqual(second.repetitions, 2)
        # The date is the interval nudged by a few per cent; the interval
        # itself is exact.
        drift = second.due_date - (NOW + timedelta(days=second.interval_days))
        self.assertLessEqual(abs(drift.total_seconds()),
                             second.interval_days * 86400 * SM2Scheduler.FUZZ)

    def test_a_miss_resets_the_interval_but_only_nudges_the_ease(self) -> None:
        card = self.scheduler.new_card(Unit.lemma("haus"), NOW)
        card = self.scheduler.review(card, correct=True, now=NOW)
        missed = self.scheduler.review(card, correct=False, now=NOW)
        self.assertEqual(missed.interval_days, 1.0)
        self.assertEqual(missed.repetitions, 0)
        self.assertAlmostEqual(missed.ease_factor, 2.55 - 0.15)

    def test_ease_stays_within_bounds(self) -> None:
        card = Card(unit=Unit.lemma("x"), due_date=NOW, ease_factor=1.35)
        for _ in range(5):
            card = self.scheduler.review(card, correct=False, now=NOW)
        self.assertAlmostEqual(card.ease_factor, SM2Scheduler.MIN_EASE)
        for _ in range(50):
            card = self.scheduler.review(card, correct=True, now=NOW)
        self.assertAlmostEqual(card.ease_factor, SM2Scheduler.MAX_EASE)

    def test_the_interval_is_capped_so_a_mastered_card_still_schedules(self) -> None:
        """Geometric growth overflows timedelta after ~40 correct answers."""
        card = self.scheduler.new_card(Unit.lemma("x"), NOW)
        for _ in range(200):
            card = self.scheduler.review(card, correct=True, now=NOW)
        self.assertEqual(card.interval_days, SM2Scheduler.MAX_INTERVAL_DAYS)
        self.assertGreater(card.due_date, NOW)


    def test_cards_claimed_together_stop_coming_back_together(self) -> None:
        """A batch is minted off one `now` and grows by one ease, so
        without a nudge every card in it is asked on the same day for as
        long as it lives."""
        units = [Unit.lemma(f"wort{n}") for n in range(20)]
        dates = set()
        for unit in units:
            card = self.scheduler.new_card(unit, NOW)
            for _ in range(3):
                card = self.scheduler.review(card, correct=True, now=NOW)
            dates.add(card.due_date)
        self.assertEqual(len(dates), len(units))
        # Nudged, not rescheduled: still within a few per cent of the day
        # the interval asks for.
        exact = NOW + timedelta(days=2.5 * 2.55 * 2.6)
        for date in dates:
            self.assertLessEqual(abs((date - exact).total_seconds()),
                                 (exact - NOW).total_seconds() * SM2Scheduler.FUZZ)

    def test_the_same_history_always_lands_on_the_same_day(self) -> None:
        """Drawn from the unit and its passes, not from chance -- two
        loads of the page must not move a card that was not reviewed."""
        def schedule() -> datetime:
            card = self.scheduler.new_card(Unit.lemma("haus"), NOW)
            for _ in range(3):
                card = self.scheduler.review(card, correct=True, now=NOW)
            return card.due_date
        self.assertEqual(schedule(), schedule())
        self.assertEqual(schedule(), SM2Scheduler().review(
            self.scheduler.review(
                self.scheduler.review(
                    self.scheduler.new_card(Unit.lemma("haus"), NOW),
                    correct=True, now=NOW),
                correct=True, now=NOW),
            correct=True, now=NOW).due_date)

    def test_a_missed_card_comes_back_tomorrow_exactly(self) -> None:
        """The reset a miss gives is the one interval under the floor:
        tomorrow, not tomorrow give or take. Every interval a pass gives
        starts at 2.5 days and is nudged."""
        card = self.scheduler.new_card(Unit.lemma("haus"), NOW)
        first = self.scheduler.review(card, correct=True, now=NOW)
        self.assertNotEqual(first.due_date, NOW + timedelta(days=2.5))
        missed = self.scheduler.review(first, correct=False, now=NOW)
        self.assertEqual(missed.interval_days, 1.0)
        self.assertEqual(missed.due_date, NOW + timedelta(days=1.0))

    def test_the_hearing_ladder_is_not_jittered_with_it(self) -> None:
        """`vocab.encounters` reads the intervals a perfect run gives to
        lay out its rungs. The nudge is on the date, so the ladder that
        the passive half climbs still matches the active schedule."""
        from vocab.encounters import LADDER
        card = self.scheduler.new_card(Unit.lemma("x"), NOW)
        waits = [0.0]
        while len(waits) < len(LADDER):
            waits.append(card.interval_days)
            card = self.scheduler.review(card, correct=True, now=card.due_date)
        self.assertEqual(list(LADDER), waits)


class PromptBuilderTest(unittest.TestCase):
    def test_word_cards_blank_the_surface_form_not_the_lemma(self) -> None:
        unit = Unit.lemma("haben")
        index = ExampleIndex([sentence("Er hat ein Buch.", unit, "hat", "He has a book.")])
        prompt = PromptBuilder(index).build(Card(unit, NOW), frozenset())
        self.assertEqual(prompt.cloze, ("Er _____ ein Buch.",))
        self.assertFalse(prompt.self_graded)
        self.assertIn("      He has a book.", prompt.question_lines())

    def test_pattern_cards_withhold_the_german(self) -> None:
        unit = Unit.pattern("jdm. (Dat) etw. (Akk) geben")
        index = ExampleIndex([sentence("Er gab es mir.", unit, "gab", "He gave it to me.")])
        prompt = PromptBuilder(index).build(Card(unit, NOW), frozenset())
        self.assertTrue(prompt.self_graded)
        self.assertEqual(prompt.cloze, ())
        joined = " ".join(prompt.question_lines())
        self.assertIn("He gave it to me.", joined)
        self.assertNotIn("Er gab es mir.", joined)
        self.assertIn("   Er gab es mir.", prompt.answer_lines())

    def test_examples_prefer_sentences_the_learner_can_read(self) -> None:
        unit = Unit.lemma("haus")
        easy = sentence("Das Haus.", unit, "Haus")
        hard = sentence("Das exorbitante Haus.", unit, "Haus",
                        extra={Unit.lemma("exorbitant")})
        index = ExampleIndex([hard, easy])
        chosen = index.examples(unit, frozenset(), limit=1)
        self.assertEqual(chosen[0].text, "Das Haus.")

    def test_missing_surface_falls_back_to_the_plain_sentence(self) -> None:
        unit = Unit.lemma("haus")
        plain = Sentence(text="Das Haus.").with_units(frozenset({unit}))
        prompt = PromptBuilder(ExampleIndex([plain])).build(Card(unit, NOW), frozenset())
        self.assertEqual(prompt.cloze, ("Das Haus.",))


class ReviewSessionTest(unittest.TestCase):
    def test_blank_input_skips_without_rescheduling(self) -> None:
        unit = Unit.lemma("haus")
        card = Card(unit, NOW, card_id=1)
        saved: list[Card] = []
        store = _FakeStore([card], saved)
        index = ExampleIndex([sentence("Das Haus.", unit, "Haus")])
        session = ReviewSession(store, SM2Scheduler(), PromptBuilder(index),
                                read=lambda _="": "", write=lambda _: None)
        report = session.run(frozenset(), now=NOW)
        self.assertEqual((report.reviewed, report.skipped), (0, 1))
        self.assertEqual(saved, [])

    def test_a_correct_answer_is_graded_and_stored(self) -> None:
        unit = Unit.lemma("haus")
        saved: list[Card] = []
        store = _FakeStore([Card(unit, NOW, card_id=1)], saved)
        index = ExampleIndex([sentence("Das Haus.", unit, "Haus")])
        session = ReviewSession(store, SM2Scheduler(), PromptBuilder(index),
                                read=lambda _="": "HAUS", write=lambda _: None)
        report = session.run(frozenset(), now=NOW)
        self.assertEqual((report.reviewed, report.correct), (1, 1))
        self.assertEqual(len(saved), 1)
        self.assertGreater(saved[0].due_date, NOW)


class _FakeStore:
    def __init__(self, cards: list[Card], saved: list[Card]) -> None:
        self._cards = cards
        self._saved = saved

    def due(self, now, limit=20):
        return self._cards[:limit]

    def save(self, card):
        self._saved.append(card)


if __name__ == "__main__":
    unittest.main()
