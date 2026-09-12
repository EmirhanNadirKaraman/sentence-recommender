"""What a corpus can eventually teach, and what stepping off the list costs.

Reachability does not depend on the order words are taught in: learning a
word never makes another harder to reach, so the walk's choice of what to
teach next cannot change *whether* a goal is reachable. That is why the free
part of this is a closure rather than a walk.

The budget is the part that is not free, and there the order does matter --
spending it on the wrong words reaches fewer goals -- so it is chosen rather
than taken as it comes. These tests pin both halves.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from roadmap.reach import reachable
from vocab.entry import Unit


@dataclass(frozen=True)
class _Sentence:
    units: frozenset


def s(*keys: str) -> _Sentence:
    return _Sentence(frozenset(Unit("lemma", k) for k in keys))


def u(key: str) -> Unit:
    return Unit("lemma", key)


class HeldTest(unittest.TestCase):
    """budget=0 -- the walk may only ever teach goals."""

    def test_a_goal_alone_with_known_words_is_reached(self) -> None:
        got = reachable([s("ich", "goal")], {u("ich")}, {u("goal")}, budget=0)
        self.assertIn(u("goal"), got)

    def test_a_goal_behind_an_off_list_word_is_not(self) -> None:
        got = reachable([s("ich", "spam", "goal")], {u("ich")},
                        {u("goal")}, budget=0)
        self.assertNotIn(u("goal"), got)
        self.assertNotIn(u("spam"), got)

    def test_a_goal_can_unlock_another_goal(self) -> None:
        """The closure runs to a fixpoint rather than one pass."""
        got = reachable([s("ich", "one"), s("ich", "one", "two")],
                        {u("ich")}, {u("one"), u("two")}, budget=0)
        self.assertIn(u("two"), got)

    def test_two_unknowns_teach_nothing(self) -> None:
        got = reachable([s("ich", "one", "two")], {u("ich")},
                        {u("one"), u("two")}, budget=0)
        self.assertNotIn(u("one"), got)

    def test_the_known_set_comes_back_untouched(self) -> None:
        got = reachable([], {u("ich")}, {u("goal")}, budget=0)
        self.assertEqual(got, {u("ich")})


class BudgetTest(unittest.TestCase):
    """A budget buys off-list words, most useful first."""

    def test_one_word_of_budget_clears_one_blocker(self) -> None:
        """The blocker needs a sentence of its own to be learnable from.

        Nothing here ever learns a word except as the single unknown in some
        sentence, budget or no budget — the budget says a word off the list
        may be taken, not that it may be taken from anywhere. A blocker
        standing beside another unknown is not i+1 and cannot be bought.
        """
        sentences = [s("ich", "spam"),              # spam is i+1 here
                     s("ich", "spam", "goal")]      # so goal follows there
        got = reachable(sentences, {u("ich")}, {u("goal")}, budget=1)
        self.assertIn(u("spam"), got)
        self.assertIn(u("goal"), got)

    def test_a_blocker_that_is_never_alone_cannot_be_bought(self) -> None:
        """However large the budget. This is the shape of a genuinely
        stranded goal, and no amount of willingness reaches it."""
        sentences = [s("ich", "spam", "goal")]
        got = reachable(sentences, {u("ich")}, {u("goal")}, budget=1000)
        self.assertNotIn(u("goal"), got)
        self.assertNotIn(u("spam"), got)

    def test_it_does_not_overspend(self) -> None:
        """Two blockers, one word of budget: only one is bought."""
        sentences = [s("ich", "spam"), s("ich", "spam", "one"),
                     s("ich", "ham"), s("ich", "ham", "two")]
        got = reachable(sentences, {u("ich")}, {u("one"), u("two")}, budget=1)
        bought = {x for x in got if x.key in ("spam", "ham")}
        self.assertEqual(len(bought), 1)

    def test_it_buys_the_word_that_unlocks_the_most(self) -> None:
        """`ham` is the only unknown in two sentences, `spam` in one, so a
        single word of budget should go on `ham`."""
        sentences = [s("ich", "spam"), s("ich", "ham"), s("du", "ham")]
        got = reachable(sentences, {u("ich"), u("du")}, set(), budget=1)
        self.assertIn(u("ham"), got)
        self.assertNotIn(u("spam"), got)

    def test_buying_a_word_can_cascade_into_free_goals(self) -> None:
        """One off-list word bought, then goals fall out of it for nothing."""
        sentences = [s("ich", "spam"), s("ich", "spam", "one"),
                     s("ich", "one", "two")]
        got = reachable(sentences, {u("ich")}, {u("one"), u("two")}, budget=1)
        self.assertIn(u("one"), got)
        self.assertIn(u("two"), got)

    def test_a_budget_with_nothing_to_buy_is_harmless(self) -> None:
        got = reachable([s("ich", "goal")], {u("ich")}, {u("goal")}, budget=99)
        self.assertEqual(got, {u("ich"), u("goal")})

    def test_ties_do_not_depend_on_iteration_order(self) -> None:
        """Two equally useful words: the same one is bought every time, or
        the page's number would wobble between reloads."""
        sentences = [s("ich", "aaa"), s("ich", "bbb")]
        picks = {frozenset(reachable(sentences, {u("ich")}, set(), budget=1))
                 for _ in range(5)}
        self.assertEqual(len(picks), 1)


if __name__ == "__main__":
    unittest.main()
