"""What the hunt remembers between rounds, which used to be nothing.

Three rounds of eight candidates added six videos, because `gather` filtered
only on what was already in the catalogue: the same six subtitle-less videos
were offered, fetched and refused in every round, and `take` collected the
refusals into `Hunt.refused` and dropped them when the command ended.

Stubbed throughout — no network, no database, no ingestor.
"""
from __future__ import annotations

import unittest
from unittest import mock

from ingest.attempts import SETTLED
from ingest.hunt import Hunt, VideoHunter
from vocab.entry import Unit


class FakeIngestor:
    def __init__(self, held=(), refuse=()) -> None:
        self.held = set(held)
        self.refuse = set(refuse)
        self.asked: list[str] = []

    def already_have(self, video_id: str) -> bool:
        return video_id in self.held

    def add(self, video_id: str, language=None):
        self.asked.append(video_id)
        if video_id in self.refuse:
            # The shape the hunt actually meets. It classifies `unfetchable`
            # — never settled, because it cannot be told from throttling.
            raise SystemExit(f"{video_id}: no de subtitles came back, and "
                             "the video could not be inspected to say why.")
        self.held.add(video_id)
        return type("Landed", (), {"lines": 100, "title": video_id})()


class FakeLog:
    def __init__(self, settled=()) -> None:
        self._settled = frozenset(settled)
        self.written: list[tuple[str, str]] = []

    def settled(self):
        return self._settled

    def record(self, video_id, outcome, detail="") -> None:
        self.written.append((video_id, outcome))


class RememberingTest(unittest.TestCase):
    def setUp(self) -> None:
        # `take` pauses between videos to be civil to YouTube. Nothing here
        # touches the network, and eleven seconds of politeness in a suite
        # that otherwise runs in a fifth of a second is worth stubbing.
        patched = mock.patch("ingest.hunt.time.sleep")
        patched.start()
        self.addCleanup(patched.stop)

    def hunter(self, ingestor, log=None, results=()):
        hunter = VideoHunter(ingestor, log)
        hunter.search = lambda term, limit=None: list(results)
        return hunter

    def test_a_refusal_is_written_down(self) -> None:
        """It was collected into `Hunt.refused` and dropped."""
        log = FakeLog()
        hunter = self.hunter(FakeIngestor(refuse={"bad"}), log)
        hunter.take(Hunt(candidates=["bad"]), say=lambda *a, **k: None)
        self.assertEqual(log.written, [("bad", "unfetchable")])

    def test_a_plain_missing_subtitle_settles(self) -> None:
        """Unlike the inspect-failed shape, this one is a verdict."""
        log = FakeLog()
        hunter = self.hunter(FakeIngestor(), log)

        def refuse(video_id, language=None):
            raise SystemExit(f"{video_id}: no de subtitles came back.")

        hunter._ingestor.add = refuse
        hunter.take(Hunt(candidates=["none"]), say=lambda *a, **k: None)
        self.assertEqual(log.written, [("none", "no-subtitles")])
        self.assertIn("none", hunter._settled)

    def test_so_is_a_success(self) -> None:
        log = FakeLog()
        hunter = self.hunter(FakeIngestor(), log)
        hunter.take(Hunt(candidates=["good"]), say=lambda *a, **k: None)
        self.assertEqual(log.written, [("good", "added")])

    def test_a_refused_video_is_not_offered_again(self) -> None:
        """The whole bug: round two re-fetched round one's failures.

        The refusal here is `unfetchable`, so this is the run-local `_tried`
        set doing the work, not the settled list."""
        ingestor = FakeIngestor(refuse={"bad"})
        hunter = self.hunter(ingestor, FakeLog(), results=["bad", "good"])
        hunter.take(Hunt(candidates=["bad"]), say=lambda *a, **k: None)
        again = hunter.gather([Unit("lemma", "haus")], wanted=5)
        self.assertNotIn("bad", again.candidates)
        self.assertIn("good", again.candidates)

    def test_a_settled_video_is_never_offered(self) -> None:
        hunter = self.hunter(FakeIngestor(), FakeLog(settled={"old"}),
                             results=["old", "new"])
        self.assertEqual(
            hunter.gather([Unit("lemma", "haus")], wanted=5).candidates, ["new"])

    def test_what_is_already_held_is_still_skipped(self) -> None:
        hunter = self.hunter(FakeIngestor(held={"have"}), FakeLog(),
                             results=["have", "want"])
        self.assertEqual(
            hunter.gather([Unit("lemma", "haus")], wanted=5).candidates, ["want"])

    def test_recording_a_settled_outcome_closes_it_immediately(self) -> None:
        """Without this the same run could still offer it again."""
        hunter = self.hunter(FakeIngestor(), FakeLog())
        settled = next(iter(SETTLED))
        hunter._record("shut", settled)
        self.assertIn("shut", hunter._settled)

    def test_unfetchable_is_not_settled(self) -> None:
        """It cannot be told from throttling, and blacklisting it once cost
        forty good videos — so it is skipped for this run only."""
        self.assertNotIn("unfetchable", SETTLED)
        hunter = self.hunter(FakeIngestor(), FakeLog())
        hunter._record("maybe", "unfetchable")
        self.assertNotIn("maybe", hunter._settled)

    def test_it_works_without_a_log_at_all(self) -> None:
        hunter = self.hunter(FakeIngestor(refuse={"bad"}), None)
        hunter.take(Hunt(candidates=["bad"]), say=lambda *a, **k: None)
        self.assertIn("bad", hunter._tried)
