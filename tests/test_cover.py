"""The video cover — the model, not the solver.

Two things in it are easy to get wrong and invisible in a solver that
reports Optimal. The constraint counts sentences rather than videos, so one
video may satisfy a word alone; and a word with fewer sentences than asked
for must be asked for what exists, or the model is infeasible and there is
no cover at all rather than a cover with a shortfall.

`audit` is what these lean on. It re-counts the answer against the pool
without asking the solver anything, which is the only way a wrong model
shows up as wrong.
"""
from __future__ import annotations

import unittest
from unittest import mock

import roadmap.cover as cover_module
from roadmap.cover import Cover, audit
from vocab.entry import Unit


def u(key: str) -> Unit:
    """Real units, because `solve` sorts the unreachable ones by kind and
    key. Strings stood in here once and only the one test that reached that
    sort noticed."""
    return Unit("lemma", key)


class AuditTest(unittest.TestCase):
    def test_a_satisfied_cover_is_silent(self) -> None:
        held = {u("a"): {"v1": 5}, u("b"): {"v1": 2, "v2": 3}}
        self.assertEqual(audit(Cover(videos=("v1", "v2")), held), [])

    def test_one_video_may_satisfy_a_word_alone(self) -> None:
        """The coefficient is sentences, not videos: v1 brings five."""
        self.assertEqual(audit(Cover(videos=("v1",)), {u("a"): {"v1": 5}}), [])

    def test_a_missing_video_is_reported(self) -> None:
        held = {u("a"): {"v1": 2, "v2": 3}}
        self.assertEqual(audit(Cover(videos=("v1",)), held), [(u("a"), 2, 5)])

    def test_a_word_is_only_asked_for_what_exists(self) -> None:
        """Three sentences anywhere means three, not five — otherwise the
        model is infeasible and returns nothing at all."""
        self.assertEqual(audit(Cover(videos=("v1",)), {u("a"): {"v1": 3}}), [])

    def test_and_it_still_has_to_get_them(self) -> None:
        held = {u("a"): {"v1": 1, "v2": 2}}
        self.assertEqual(audit(Cover(videos=("v1",)), held), [(u("a"), 1, 3)])

    def test_depth_is_respected(self) -> None:
        held = {u("a"): {"v1": 2}}
        self.assertEqual(audit(Cover(videos=("v1",)), held, depth=2), [])
        self.assertEqual(audit(Cover(), held, depth=2), [(u("a"), 0, 2)])

    def test_an_empty_cover_fails_everything_it_should(self) -> None:
        held = {u("a"): {"v1": 9}, u("b"): {"v2": 1}}
        self.assertEqual(
            sorted(audit(Cover(), held), key=lambda row: row[0].key),
            [(u("a"), 0, 5), (u("b"), 0, 1)])


class SolveTest(unittest.TestCase):
    """The real solver on models small enough to reason about by hand."""

    def solve(self, held, minutes, goals=None, **kw):
        with mock.patch.object(cover_module, "supply",
                               lambda *a, **k: held):
            return cover_module.solve(
                None, [], frozenset(goals or held), minutes,
                say=lambda *a, **k: None, **kw)

    def test_it_prefers_the_shorter_of_two_that_both_work(self) -> None:
        got = self.solve({u("a"): {"long": 5, "short": 5}},
                         {"long": 90.0, "short": 10.0})
        self.assertEqual(got.videos, ("short",))
        self.assertEqual(got.minutes, 10.0)

    def test_it_takes_the_overlap_when_that_is_cheaper(self) -> None:
        """One video serving both beats two serving one each."""
        got = self.solve({u("a"): {"both": 5, "just_a": 5},
                          u("b"): {"both": 5, "just_b": 5}},
                         {"both": 30.0, "just_a": 20.0, "just_b": 20.0})
        self.assertEqual(got.videos, ("both",))

    def test_a_thin_word_does_not_make_it_infeasible(self) -> None:
        got = self.solve({u("a"): {"v": 5}, u("thin"): {"v": 1}}, {"v": 10.0})
        self.assertEqual(got.status, "Optimal")
        self.assertEqual(got.short, {u("thin"): (1, 1)})

    def test_a_word_with_no_video_is_unreachable_not_fatal(self) -> None:
        got = self.solve({u("a"): {"v": 5}}, {"v": 10.0},
                         goals={u("a"), u("nowhere")})
        self.assertEqual(got.videos, ("v",))
        self.assertEqual(got.unreachable, (u("nowhere"),))

    def test_the_answer_survives_its_own_audit(self) -> None:
        held = {u("a"): {"x": 3, "y": 4}, u("b"): {"y": 5}, u("c"): {"x": 1}}
        self.assertEqual(audit(self.solve(held, {"x": 12.0, "y": 30.0}),
                               held), [])
