"""When a video stops being worth asking about.

Two failures are in tension here. Settling an ambiguous refusal at once
wrote off forty good videos, because `unfetchable` cannot tell a deleted
video from a throttled request. But never settling it is its own bug: a
second pass over a channel spent its first thirty-four videos re-asking
questions the first pass had already failed to answer, and a third would
have done the same.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ingest.attempts import SETTLED, AttemptLog


class SettlingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = AttemptLog(Path(self._dir.name) / "state.sqlite3")

    def test_a_definite_verdict_settles_at_once(self) -> None:
        self.log.record("gone", "no-subtitles", "nothing hand-written")
        self.assertIn("gone", self.log.settled())

    def test_an_ambiguous_one_does_not(self) -> None:
        """It cannot tell a deleted video from a throttled request."""
        self.log.record("maybe", "unfetchable", "could not be inspected")
        self.assertNotIn("maybe", self.log.settled())

    def test_but_it_settles_after_repeated_failure(self) -> None:
        for _ in range(AttemptLog.GIVE_UP):
            self.log.record("maybe", "unfetchable", "again")
        self.assertIn("maybe", self.log.settled())

    def test_one_short_of_the_limit_is_still_open(self) -> None:
        for _ in range(AttemptLog.GIVE_UP - 1):
            self.log.record("maybe", "unfetchable", "again")
        self.assertNotIn("maybe", self.log.settled())

    def test_a_video_that_worked_is_never_settled(self) -> None:
        """However many times it is seen — it is in the catalogue, and
        `already_have` is what keeps it from being fetched twice."""
        for _ in range(AttemptLog.GIVE_UP + 2):
            self.log.record("good", "added")
        self.assertNotIn("good", self.log.settled())

    def test_a_later_success_is_what_the_log_remembers(self) -> None:
        self.log.record("late", "unfetchable", "throttled")
        self.log.record("late", "added")
        self.assertNotIn("late", self.log.settled())

    def test_counts_survive_a_new_log_over_the_same_file(self) -> None:
        path = Path(self._dir.name) / "state.sqlite3"
        for _ in range(AttemptLog.GIVE_UP):
            AttemptLog(path).record("maybe", "unfetchable")
        self.assertIn("maybe", AttemptLog(path).settled())

    def test_unfetchable_is_still_not_in_the_settled_outcomes(self) -> None:
        """The repeat rule is what settles it, not the outcome itself."""
        self.assertNotIn("unfetchable", SETTLED)


class ClassifyingTest(unittest.TestCase):
    """Which refusals are verdicts and which are weather.

    Getting this wrong is expensive in both directions, and it has been wrong
    in both. Calling weather a verdict wrote off forty good videos. Calling a
    verdict weather is quieter and was live for longer: 526 MrWissen2go
    videos with only auto-generated captions classified as `error`, which is
    never settled, so every run re-fetched all of them.
    """

    def test_auto_generated_captions_are_a_verdict(self) -> None:
        """The one that was missed. `_why_empty` writes "captions" — it is
        YouTube's word for the auto track — so the `subtitle` test never saw
        it and it fell through to `error`, which is never settled. Fetching
        it again will not make the track hand-written."""
        outcome = AttemptLog.classify(
            "only auto-generated de captions, which are not used — they "
            "mangle the endings you are learning.")
        self.assertEqual(outcome, "no-subtitles")
        self.assertIn(outcome, SETTLED)

    def test_no_hand_written_track_is_a_verdict(self) -> None:
        outcome = AttemptLog.classify(
            "no hand-written subtitles at all, in any language.")
        self.assertIn(outcome, SETTLED)

    def test_a_refusal_to_say_why_is_still_weather(self) -> None:
        """Deliberately not settled: a throttled burst arrives looking
        exactly like a verdict, and this is the shape it arrives in."""
        outcome = AttemptLog.classify(
            "no de subtitles came back, and the video could not be "
            "inspected to say why.")
        self.assertEqual(outcome, "unfetchable")
        self.assertNotIn(outcome, SETTLED)

    def test_a_sign_in_demand_is_weather(self) -> None:
        self.assertEqual(
            AttemptLog.classify("Sign in to confirm you're not a bot"),
            "blocked")


class AttemptedTest(unittest.TestCase):
    """Tried-and-failed is its own category, and not an opportunity.

    `sample-channel` counted 527 MrWissen2go videos as untried when 526 of
    them had already been fetched and refused, and reported that the channel
    held 66 usable videos. It held one.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = AttemptLog(Path(self._dir.name) / "state.sqlite3")

    def test_a_failure_counts_as_attempted(self) -> None:
        self.log.record("bad", "unfetchable", "no subtitles came back")
        self.assertIn("bad", self.log.attempted())

    def test_a_success_does_not(self) -> None:
        """It is in the catalogue; `already_have` is what covers it."""
        self.log.record("good", "added")
        self.assertNotIn("good", self.log.attempted())

    def test_attempted_is_wider_than_settled(self) -> None:
        """One failure is not enough to settle, but it is enough to stop the
        video being called untried."""
        self.log.record("once", "unfetchable", "throttled")
        self.assertIn("once", self.log.attempted())
        self.assertNotIn("once", self.log.settled())

    def test_a_video_never_seen_is_in_neither(self) -> None:
        self.assertNotIn("unknown", self.log.attempted())
        self.assertNotIn("unknown", self.log.settled())


class AutoSettledTest(unittest.TestCase):
    """What settles a video depends on which path is asking.

    `no-subtitles` means "no hand-written track". For the ordinary path that
    is a permanent verdict; for the machine-caption path it is the entry
    condition, and skipping those would skip every video the path exists for
    — on a channel with no manual subtitles anywhere, all of them.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = AttemptLog(Path(self._dir.name) / "state.sqlite3")

    def test_no_hand_written_track_stops_settling_it(self) -> None:
        self.log.record("auto-only", "no-subtitles", "auto-generated only")
        self.assertIn("auto-only", self.log.settled())
        self.assertNotIn("auto-only", self.log.settled(accept_auto=True))

    def test_a_gate_verdict_settles_it(self) -> None:
        """An unpunctuated track will not have acquired punctuation tomorrow."""
        for outcome in ("auto-unpunctuated", "auto-not-german",
                        "auto-no-track", "auto-too-short"):
            self.log.record(outcome, outcome, "refused by the gate")
            self.assertIn(outcome, self.log.settled(accept_auto=True))

    def test_a_gone_video_settles_on_both_paths(self) -> None:
        self.log.record("gone", "unavailable", "withdrawn")
        self.assertIn("gone", self.log.settled())
        self.assertIn("gone", self.log.settled(accept_auto=True))

    def test_a_throttled_request_settles_on_neither(self) -> None:
        """The trap this whole class of bug came from: a refusal that
        explains nothing is weather, and writing it off once cost nine
        videos nobody had checked."""
        self.log.record("throttled", "unfetchable", "page needs to be reloaded")
        self.assertNotIn("throttled", self.log.settled())
        self.assertNotIn("throttled", self.log.settled(accept_auto=True))

    def test_three_failures_settle_it_on_either_path(self) -> None:
        for _ in range(AttemptLog.GIVE_UP):
            self.log.record("stubborn", "unfetchable", "still nothing")
        self.assertIn("stubborn", self.log.settled())
        self.assertIn("stubborn", self.log.settled(accept_auto=True))
