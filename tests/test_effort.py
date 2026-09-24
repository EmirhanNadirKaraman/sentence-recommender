"""Knuth's generalisation of Dijkstra, over the corpus hypergraph."""
from __future__ import annotations

import unittest

from roadmap.effort import BOTTLENECK, CHAIN, effort
from roadmap.reach import reachable
from vocab.entry import Unit


def u(key: str) -> Unit:
    return Unit("lemma", key)


class Toy:
    """V1 (10 min) says A · V2 (10 min) says B · V3 (5 min) says 'A B X'."""

    priced = [(10.0, {u("A")}), (10.0, {u("B")}),
              (5.0, {u("A"), u("B"), u("X")})]


class ConjunctionTest(unittest.TestCase):
    """The thing plain Dijkstra gets wrong."""

    def test_the_chain_pays_for_every_prerequisite(self) -> None:
        """Dijkstra over words relaxes X from its cheapest neighbour and says
        15. X needs A *and* B, so the honest answer is 10 + 10 + 5."""
        got = effort(Toy.priced, set(), CHAIN)
        self.assertEqual(got[u("X")], 25.0)

    def test_the_bottleneck_is_the_longest_video_on_the_way(self) -> None:
        got = effort(Toy.priced, set(), BOTTLENECK)
        self.assertEqual(got[u("X")], 10.0)

    def test_the_lower_bound_never_exceeds_the_upper(self) -> None:
        low = effort(Toy.priced, set(), BOTTLENECK)
        high = effort(Toy.priced, set(), CHAIN)
        for unit, value in low.items():
            self.assertLessEqual(value, high[unit], unit.key)

    def test_what_is_known_is_free_and_carries_nothing(self) -> None:
        got = effort(Toy.priced, {u("A"), u("B")}, CHAIN)
        self.assertEqual(got[u("A")], 0.0)
        self.assertEqual(got[u("X")], 5.0)   # only the video that says it

    def test_a_cheaper_route_displaces_a_dearer_one(self) -> None:
        """The reason this needs a queue rather than `reach.py`'s work list."""
        priced = [(10.0, {u("A")}), (1.0, {u("A")}),
                  (2.0, {u("A"), u("X")})]
        self.assertEqual(effort(priced, set(), CHAIN)[u("A")], 1.0)
        self.assertEqual(effort(priced, set(), CHAIN)[u("X")], 3.0)


class AgreesWithReachTest(unittest.TestCase):
    """It must settle exactly what `reach.py` calls reachable, and no more.

    The two answer different questions -- one whether, one how dear -- over
    the same structure, so a word one finds and the other does not is a bug
    in whichever is wrong.
    """

    class Line:
        def __init__(self, units):
            self.units = frozenset(units)
            self.text = " ".join(sorted(x.key for x in units))

    def corpus(self):
        return [self.Line({u("A")}),
                self.Line({u("A"), u("B")}),
                self.Line({u("A"), u("B"), u("C")}),
                self.Line({u("D"), u("E")})]          # neither ever settles

    def test_the_same_units_settle(self) -> None:
        lines = self.corpus()
        goals = frozenset({u(k) for k in "ABCDE"})
        reached = reachable(lines, set(), goals, budget=0,
                            compounds=_NoCompounds())
        priced = effort([(1.0, line.units) for line in lines], set())
        self.assertEqual({x for x in goals if x in reached},
                         {x for x in goals if x in priced})

    def test_a_word_with_no_way_in_is_absent(self) -> None:
        priced = effort([(1.0, line.units) for line in self.corpus()], set())
        self.assertNotIn(u("D"), priced)
        self.assertNotIn(u("E"), priced)


class _NoCompounds:
    """`reachable` grants compounds; this experiment is about sentences."""

    def derivable(self, known):
        return set()

    def unlocked_by(self, unit, known):
        return ()


if __name__ == "__main__":
    unittest.main()
