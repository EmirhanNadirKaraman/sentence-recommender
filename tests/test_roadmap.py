"""The greedy walk and the incremental index it runs on.

The index maintains unknown counts, the frontier and the lookahead by hand as
units are learned.  A cross-check against a recomputed-from-scratch version is
the point of these tests: an incremental structure that drifts would still
produce a plausible-looking roadmap.
"""
from __future__ import annotations

import unittest

from corpus.sentence import Sentence
from roadmap import CorpusIndex, KnownSet, RoadmapBuilder, UnitPriority
from vocab.entry import Unit


def sentence(text: str, *keys: str) -> Sentence:
    return Sentence(text=text).with_units(frozenset(Unit.lemma(k) for k in keys))


class CorpusIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sentences = [
            sentence("a", "ich", "sein"),              # 0 unknown
            sentence("b", "ich", "sein", "haus"),      # 1 unknown  -> frontier
            sentence("c", "ich", "haus", "baum"),      # 2 unknown  -> lookahead
            sentence("d", "ich", "haus", "baum", "x"),  # 3 unknown
        ]
        self.known = KnownSet({Unit.lemma("ich"), Unit.lemma("sein")})
        self.index = CorpusIndex(self.sentences, self.known)

    def test_initial_state(self) -> None:
        self.assertEqual(self.index.readable, 1)
        self.assertEqual(list(self.index.candidates()), [Unit.lemma("haus")])
        self.assertEqual(self.index.unlocks(Unit.lemma("haus")), 1)
        self.assertEqual(self.index.unlocks(Unit.lemma("baum")), 1)

    def test_learning_moves_every_state(self) -> None:
        self.index.learn(Unit.lemma("haus"))
        self.assertEqual(self.index.readable, 2)          # "b" became readable
        self.assertEqual(self.index.unknown_count(2), 1)  # "c" joined frontier
        self.assertEqual(self.index.unknown_count(3), 2)  # "d" joined lookahead
        self.assertEqual(list(self.index.candidates()), [Unit.lemma("baum")])
        self.assertEqual(self.index.unlocks(Unit.lemma("baum")), 1)
        self.assertEqual(self.index.unlocks(Unit.lemma("x")), 1)

    def test_incremental_state_matches_a_fresh_rebuild(self) -> None:
        """Learning step by step must leave the index where a rebuild would.

        The comparison is built from the index's own `known`, not from the set
        it was constructed with: the index does not write back into that, so
        it still describes the starting position.
        """
        for key in ("haus", "baum", "x"):
            self.index.learn(Unit.lemma(key))
            rebuilt = CorpusIndex(self.sentences, KnownSet(self.index.known))
            self.assertEqual(self.index.readable, rebuilt.readable)
            self.assertEqual(
                {u: sorted(p) for u, p in self.index.candidates().items()},
                {u: sorted(p) for u, p in rebuilt.candidates().items()},
            )
            for unit in {u for s in self.sentences for u in s.units}:
                self.assertEqual(
                    self.index.unlocks(unit), rebuilt.unlocks(unit),
                    msg=f"lookahead diverged for {unit} after learning {key}",
                )


class RoadmapBuilderTest(unittest.TestCase):
    def test_prefers_the_unit_that_unlocks_more(self) -> None:
        sentences = [
            sentence("one", "ich", "a"),
            sentence("two", "ich", "b"),
            sentence("three", "ich", "b", "c"),   # b also brings this to i+1
        ]
        known = KnownSet({Unit.lemma("ich")})
        index = CorpusIndex(sentences, known)
        priority = UnitPriority.build(())
        plan = RoadmapBuilder(index, priority, priority_weight=0.0).build()
        self.assertEqual(plan[0].unit, Unit.lemma("b"))
        self.assertEqual(plan[0].gain, 2)          # readable now + one unlocked

    def test_priority_outranks_a_small_gain(self) -> None:
        sentences = [sentence("one", "ich", "rare"), sentence("two", "ich", "common")]
        known = KnownSet({Unit.lemma("ich")})
        index = CorpusIndex(sentences, known)
        priority = UnitPriority.build(
            [Unit.lemma("common")] + [Unit.lemma(f"x{i}") for i in range(998)]
            + [Unit.lemma("rare")]
        )
        plan = RoadmapBuilder(index, priority, priority_weight=3.0).build()
        self.assertEqual(plan[0].unit, Unit.lemma("common"))

    def test_the_judge_chooses_the_teaching_sentence(self) -> None:
        """A walk with a judge: the sentence the judge doubts is not the one
        the step teaches with, and the walk runs at all — the first version
        of this named a variable its method never received."""
        from corpus.answers import Judged                   # noqa: PLC0415
        sentences = [sentence("Ich habe nicht kam mir das.", "ich", "haben"),
                     sentence("Ich habe einen Gast.", "ich", "haben")]
        index = CorpusIndex(sentences, KnownSet({Unit.lemma("ich")}))
        judged = Judged({"Ich habe nicht kam mir das.": 0.1}, {})
        plan = RoadmapBuilder(index, UnitPriority.build(()), judged=judged).build()
        self.assertEqual(plan[0].unit, Unit.lemma("haben"))
        self.assertEqual(plan[0].sentence.text, "Ich habe einen Gast.")

    def test_stops_when_nothing_is_i_plus_one(self) -> None:
        sentences = [sentence("hard", "a", "b", "c")]
        index = CorpusIndex(sentences, KnownSet())
        plan = RoadmapBuilder(index, UnitPriority.build(())).build()
        self.assertEqual(plan, [])

    def test_every_step_teaches_exactly_one_new_thing(self) -> None:
        sentences = [
            sentence("one", "ich", "a"),
            sentence("two", "ich", "a", "b"),
            sentence("three", "ich", "a", "b", "c"),
        ]
        known = KnownSet({Unit.lemma("ich")})
        index = CorpusIndex(sentences, known)
        seen = set(known.units)
        for step in RoadmapBuilder(index, UnitPriority.build(())).build():
            self.assertEqual(step.sentence.units - seen, {step.unit})
            seen.add(step.unit)


class UnitPriorityTest(unittest.TestCase):
    """One authored ordering ranks both kinds.

    Words and patterns compete for the same roadmap slots, so ranking them by
    unrelated measures made the comparison arbitrary. They now share a list.
    """

    def test_both_kinds_are_ranked_by_the_same_list(self) -> None:
        priority = UnitPriority.build(
            [Unit.lemma("und"), Unit.pattern("P"), Unit.lemma("selten")]
        )
        self.assertAlmostEqual(priority.of(Unit.lemma("und")), 1.0)
        self.assertGreater(priority.of(Unit.pattern("P")),
                           priority.of(Unit.lemma("selten")))

    def test_a_unit_absent_from_the_list_scores_nothing(self) -> None:
        priority = UnitPriority.build([Unit.lemma("und")])
        self.assertEqual(priority.of(Unit.lemma("unlisted")), 0.0)
        self.assertEqual(priority.of(Unit.pattern("unlisted")), 0.0)

    def test_the_first_mention_sets_the_rank(self) -> None:
        """A lemma recurs under several blueprints; the earliest one counts."""
        priority = UnitPriority.build(
            [Unit.lemma("haben"), Unit.lemma("x"), Unit.lemma("haben")]
        )
        self.assertAlmostEqual(priority.of(Unit.lemma("haben")), 1.0)


class GoalRoadmapTest(unittest.TestCase):
    """With a goal list the walk has a destination, not just a direction."""

    def setUp(self) -> None:
        self.sentences = [
            sentence("a", "ich", "gain1", "gain2"),   # two easy non-goals
            sentence("b", "ich", "gain1"),
            sentence("c", "ich", "gain2"),
            sentence("d", "ich", "goal"),             # the thing we want
        ]
        self.known = KnownSet({Unit.lemma("ich")})

    def plan(self, goals: frozenset):
        index = CorpusIndex(self.sentences, KnownSet(self.known.units))
        return RoadmapBuilder(index, UnitPriority.build(()), 0.0, goals).build()

    def test_a_goal_is_taken_before_a_higher_scoring_step(self) -> None:
        """`gain1` unlocks more, but `goal` is what we set out to learn."""
        without = self.plan(frozenset())
        self.assertNotEqual(without[0].unit, Unit.lemma("goal"))

        with_goal = self.plan(frozenset({Unit.lemma("goal")}))
        self.assertEqual(with_goal[0].unit, Unit.lemma("goal"))

    def test_ordinary_steps_still_run_once_no_goal_is_reachable(self) -> None:
        plan = self.plan(frozenset({Unit.lemma("goal")}))
        self.assertGreater(len(plan), 1)
        self.assertEqual(plan[0].unit, Unit.lemma("goal"))

    def test_a_goal_the_corpus_never_isolates_is_simply_not_reached(self) -> None:
        plan = self.plan(frozenset({Unit.lemma("absent")}))
        self.assertNotIn(Unit.lemma("absent"), {s.unit for s in plan})


if __name__ == "__main__":
    unittest.main()


class LearningTwiceTest(unittest.TestCase):
    """Learning the same unit twice must not shift the counts twice.

    The web viewer marks units known as they are read, and a unit can be
    marked again — from another page, or after a reload. A second decrement
    drives unknown counts negative, which nothing downstream checks for, so
    the frontier quietly stops meaning anything.
    """

    def setUp(self) -> None:
        self.sentences = [
            sentence("a", "ich", "haus"),
            sentence("b", "ich", "haus", "baum"),
        ]
        self.index = CorpusIndex(self.sentences, KnownSet({Unit.lemma("ich")}))

    def test_relearning_changes_nothing(self) -> None:
        self.index.learn(Unit.lemma("haus"))
        after_once = [self.index.unknown_count(i) for i in range(2)]
        readable_once = self.index.readable

        self.index.learn(Unit.lemma("haus"))

        self.assertEqual([self.index.unknown_count(i) for i in range(2)], after_once)
        self.assertEqual(self.index.readable, readable_once)

    def test_counts_never_go_negative(self) -> None:
        for _ in range(4):
            self.index.learn(Unit.lemma("haus"))
        self.assertTrue(all(self.index.unknown_count(i) >= 0 for i in range(2)))

    def test_learning_something_already_known_is_a_no_op(self) -> None:
        """`ich` was known from the start; learning it must not shift anything."""
        before = [self.index.unknown_count(i) for i in range(2)]
        self.index.learn(Unit.lemma("ich"))
        self.assertEqual([self.index.unknown_count(i) for i in range(2)], before)


class IndexOwnsItsKnownSetTest(unittest.TestCase):
    """The index must not write back into the set it was given.

    It learns as it walks, and pushing that into the caller's object
    redefines what the caller believes is known. A coverage measurement that
    read the set afterwards reported learning 33,336 units out of 7,645
    unknown ones, which is how this was found.
    """

    def test_walking_leaves_the_callers_known_set_alone(self) -> None:
        known = KnownSet({Unit.lemma("ich")})
        before = set(known.units)
        index = CorpusIndex([sentence("a", "ich", "haus")], known)

        index.learn(Unit.lemma("haus"))

        self.assertEqual(set(known.units), before)
        self.assertIn(Unit.lemma("haus"), index.known)

    def test_the_index_still_tracks_what_it_learned(self) -> None:
        index = CorpusIndex([sentence("a", "haus")], KnownSet())
        index.learn(Unit.lemma("haus"))
        self.assertEqual(index.readable, 1)
        self.assertEqual(index.unknown_count(0), 0)
