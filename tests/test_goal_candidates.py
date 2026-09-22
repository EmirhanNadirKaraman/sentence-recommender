"""The goal-only view of the frontier, maintained beside the full one.

A walk held to a study list used to scan the whole frontier every step and
reject three units in four by name. `CorpusIndex.track_goals` keeps the
narrowed map as the walk goes instead.

An incremental structure that drifts would still produce a plausible-looking
roadmap, so what is checked here is the invariant itself — the goal view must
equal the frontier filtered by the goals, key for key, set for set, in the
same order — after every path that can change either map.
"""
from __future__ import annotations

import unittest

from corpus.sentence import Sentence
from roadmap import CorpusIndex, KnownSet, RoadmapBuilder, UnitPriority
from vocab.compounds import Compounds
from vocab.entry import Unit


def sentence(text: str, *keys: str) -> Sentence:
    return Sentence(text=text).with_units(frozenset(Unit.lemma(k) for k in keys))


def u(key: str) -> Unit:
    return Unit.lemma(key)


class GoalViewInvariantTest(unittest.TestCase):
    """`goal_candidates()` == `candidates()` narrowed to the goals. Always."""

    def setUp(self) -> None:
        # Shaped so every transition the index can make is exercised: a
        # sentence already readable, one on the frontier, several in the
        # lookahead that arrive on the frontier later, and units of both
        # sorts — goals and ordinary words — mixed through them.
        self.sentences = [
            sentence("a", "ich", "sein"),                      # 0 unknown
            sentence("b", "ich", "haus"),                      # 1 -> frontier
            sentence("c", "ich", "haus", "baum"),              # 2 -> lookahead
            sentence("d", "ich", "baum", "gern"),              # 2 -> lookahead
            sentence("e", "ich", "gern"),                      # 1 -> frontier
            sentence("f", "ich", "haus", "baum", "gern"),      # 3
            sentence("g", "ich", "klausur", "baum"),           # 2, one ordinary
        ]
        self.known = KnownSet({u("ich"), u("sein")})
        self.goals = frozenset({u("haus"), u("baum"), u("gern"), u("nie")})

    def index(self) -> CorpusIndex:
        index = CorpusIndex(self.sentences, self.known, Compounds())
        index.track_goals(self.goals)
        return index

    def expected(self, index: CorpusIndex) -> dict:
        return {unit: positions
                for unit, positions in index.candidates().items()
                if unit in self.goals}

    def assert_invariant(self, index: CorpusIndex, where: str) -> None:
        view = index.goal_candidates()
        want = self.expected(index)
        self.assertEqual({k: sorted(v) for k, v in view.items()},
                         {k: sorted(v) for k, v in want.items()},
                         f"goal view drifted from the frontier {where}")
        # Order too: the walk keeps the first of equal scores, so the
        # narrowed map has to visit goals in the order the full one does.
        self.assertEqual(list(view), list(want),
                         f"goal view visits goals out of order {where}")
        # And the same set objects, not copies — a copy would stop reflecting
        # sentences added to the frontier map after it was made.
        for unit, positions in view.items():
            self.assertIs(positions, index.candidates()[unit])

    def test_invariant_holds_at_construction(self) -> None:
        index = self.index()
        self.assert_invariant(index, "at the start")
        self.assertEqual(sorted(k.key for k in index.goal_candidates()),
                         ["gern", "haus"])

    def test_invariant_holds_across_a_whole_walk(self) -> None:
        """Every mutation path, driven by learning each unit in turn.

        Covers the 1 -> 0 drop, the 2 -> 1 move that registers a unit on the
        frontier and takes it out of the lookahead, and the 3 -> 2 move that
        touches the lookahead alone.
        """
        index = self.index()
        for key in ("haus", "gern", "baum", "klausur"):
            index.learn(u(key))
            self.assert_invariant(index, f"after learning {key}")
        self.assertEqual(index.goal_candidates(), {})

    def test_a_goal_reaching_the_frontier_later_is_picked_up(self) -> None:
        """`baum` is in the lookahead at the start and arrives on the
        frontier only once `haus` is known. The view has to gain it there,
        which is the `_register` path rather than the constructor's."""
        index = self.index()
        self.assertNotIn(u("baum"), index.goal_candidates())
        index.learn(u("haus"))
        self.assertIn(u("baum"), index.goal_candidates())
        self.assert_invariant(index, "after a goal joined the frontier")

    def test_a_learned_goal_leaves_both_maps(self) -> None:
        index = self.index()
        self.assertIn(u("haus"), index.goal_candidates())
        index.learn(u("haus"))
        self.assertNotIn(u("haus"), index.candidates())
        self.assertNotIn(u("haus"), index.goal_candidates())

    def test_ordinary_units_never_enter_the_view(self) -> None:
        index = self.index()
        index.learn(u("baum"))            # puts `klausur` on the frontier
        self.assertIn(u("klausur"), index.candidates())
        self.assertNotIn(u("klausur"), index.goal_candidates())
        self.assert_invariant(index, "with an ordinary unit on the frontier")

    def test_untracked_index_keeps_an_empty_view(self) -> None:
        """An index nobody asked about goals must pay nothing and claim
        nothing — `goal_candidates()` is empty, not a copy of the frontier."""
        index = CorpusIndex(self.sentences, self.known, Compounds())
        index.learn(u("haus"))
        self.assertEqual(index.goal_candidates(), {})
        self.assertNotEqual(index.candidates(), {})

    def test_a_compound_granted_free_keeps_the_view_straight(self) -> None:
        """Learning a part can grant a compound, which walks the same
        transitions again inside one `learn`. The view must survive it."""
        sentences = [
            sentence("a", "ich", "krank"),
            sentence("b", "ich", "haus"),
            sentence("c", "ich", "krankenhaus"),
            sentence("d", "ich", "krankenhaus", "baum"),
        ]
        goals = frozenset({u("krank"), u("haus"), u("krankenhaus"), u("baum")})
        pairs = {"krankenhaus": ("krank", "haus")}
        inventory = {unit for s_ in sentences for unit in s_.units} | goals
        index = CorpusIndex(sentences, KnownSet({u("ich")}),
                            Compounds.over(inventory, pairs=pairs))
        index.track_goals(goals)
        index.learn(u("krank"))
        self.assertEqual(
            {k: sorted(v) for k, v in index.goal_candidates().items()},
            {k: sorted(v) for k, v in index.candidates().items()
             if k in goals})
        index.learn(u("haus"))            # grants `krankenhaus`
        self.assertIn(u("krankenhaus"), index.known)
        self.assertEqual(
            {k: sorted(v) for k, v in index.goal_candidates().items()},
            {k: sorted(v) for k, v in index.candidates().items()
             if k in goals})


class RoadmapEquivalenceTest(unittest.TestCase):
    """The narrowed scan must produce the plan the full scan produced.

    The reference is the old behaviour expressed exactly: recompute the
    intersection from the full frontier every time it is asked for. If the
    builder's loop gives the same answer against both, then scoring, ties and
    ordering all survived the change.
    """

    def corpus(self) -> list[Sentence]:
        # Deliberately full of ties: several goals unlock the same number of
        # sentences, so the tie-break on `unit.key` decides, and any change
        # in visiting order would show up as a different plan.
        return [
            sentence("s0", "ich", "sein"),
            sentence("s1", "ich", "alpha"),
            sentence("s2", "ich", "beta"),
            sentence("s3", "ich", "gamma"),
            sentence("s4", "ich", "delta"),
            sentence("s5", "ich", "alpha", "beta"),
            sentence("s6", "ich", "beta", "gamma"),
            sentence("s7", "ich", "gamma", "delta"),
            sentence("s8", "ich", "delta", "epsilon"),
            sentence("s9", "ich", "epsilon", "zeta"),
            sentence("s10", "ich", "zeta", "noise"),
            sentence("s11", "ich", "noise", "alpha"),
            sentence("s12", "ich", "eta", "zeta"),
            sentence("s13", "ich", "eta"),
            # `theta` is a goal the corpus never isolates: it is only ever
            # said beside `stranger`, which is not on the list and so can
            # never be taught to clear the way. A held walk strands it, which
            # is exactly the wall `--relax` exists to climb.
            sentence("s14", "ich", "theta", "stranger"),
        ]

    GOALS = frozenset({u(k) for k in
                       ("alpha", "beta", "gamma", "delta", "epsilon", "zeta",
                        "eta", "theta")})

    def plan(self, full_scan: bool, relax: bool = False) -> list:
        index = CorpusIndex(self.corpus(), KnownSet({u("ich"), u("sein")}),
                            Compounds())
        if full_scan:
            # The old loop: the goals recomputed off the whole frontier each
            # time, in the frontier's own order.
            index.goal_candidates = lambda: {          # type: ignore[method-assign]
                unit: positions
                for unit, positions in index.candidates().items()
                if unit in self.GOALS
            }
        builder = RoadmapBuilder(index, UnitPriority.build(sorted(self.GOALS,
                                                                 key=lambda x: x.key)),
                                 3.0, self.GOALS, only_goals=True, relax=relax)
        return builder.build()

    def test_the_plans_are_identical(self) -> None:
        narrowed = self.plan(full_scan=False)
        full = self.plan(full_scan=True)
        self.assertTrue(narrowed, "the walk produced no steps to compare")
        self.assertEqual([s.unit for s in narrowed], [s.unit for s in full])
        self.assertEqual([s.score for s in narrowed], [s.score for s in full])
        self.assertEqual([s.gain for s in narrowed], [s.gain for s in full])
        self.assertEqual([s.sentence.text for s in narrowed],
                         [s.sentence.text for s in full])
        self.assertEqual([s.position for s in narrowed],
                         [s.position for s in full])

    def test_a_relaxed_walk_produces_the_same_plan(self) -> None:
        """`--relax` takes two words from one sentence when nothing is one
        word away, and it scans the lookahead rather than the frontier — the
        one branch the goal view does not cover. It also learns a second unit
        per step, `beside`, which may be a goal or not, so it drives the
        index through a path the plain walk never takes."""
        narrowed = self.plan(full_scan=False, relax=True)
        full = self.plan(full_scan=True, relax=True)
        self.assertTrue(narrowed)
        # Relaxing must actually have fired, or this proves nothing.
        self.assertTrue(any(s.beside is not None for s in narrowed),
                        "no relaxed step was taken, so the branch was not tested")
        self.assertEqual([(s.unit, s.beside) for s in narrowed],
                         [(s.unit, s.beside) for s in full])
        self.assertEqual([s.score for s in narrowed], [s.score for s in full])

    def test_an_unheld_walk_still_reads_the_whole_frontier(self) -> None:
        """`only_goals=False` must be untouched: it teaches ordinary words
        to clear the way, and narrowing it would strand every goal."""
        index = CorpusIndex(self.corpus(), KnownSet({u("ich"), u("sein")}),
                            Compounds())
        plan = RoadmapBuilder(index, UnitPriority.build(()), 3.0, self.GOALS,
                              only_goals=False).build()
        taught = {s.unit for s in plan}
        self.assertIn(u("noise"), taught)
        self.assertEqual(index.goal_candidates(), {})


if __name__ == "__main__":
    unittest.main()
