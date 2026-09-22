"""What the reel reuses and what it throws away.

Two bugs, both measured on the real corpus before they were fixed:

  * `_grouped` asked the application for the corpus instead of the viewer,
    which is the same call with the same arguments — so opening the reel
    after any other page loaded a second copy of the same 214,098 sentences,
    8.88s and 650 MB, sharing not one object.

  * marking any word bumps the known-set version, which is in the score
    stamp, so every stored video score went stale — and the incremental
    repair that exists to prevent that returned early whenever the process
    held no ranking, which is every process where the word was marked from
    Next, from Review, or over MCP.

No Application, no database, no corpus: the collaborators are stubs and the
score store is a real one on a temporary file.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scores import ScoreStore
from vocab.entry import Unit
from web.handlers import Once, Viewer


def row(video: str, watch: float = 1.0) -> dict:
    return {"video": video, "title": video.title(), "lines": 99, "minutes": 5.0,
            "comprehension": 0.5, "i+1": 3, "teaches": 2, "watch": watch,
            "next": [], "level": 1.0, "readable": 0.4}


class GroupedSharesTheCorpusTest(unittest.TestCase):
    """`_grouped` must group the rows the viewer already holds."""

    def viewer(self):
        v = Viewer.__new__(Viewer)
        v._corpora = Once()
        v._videos = {}
        v._video_levels = {}
        v._spoken = {}
        v._unit_videos = {}
        v._scopes = Once()
        self.loads = []
        timed = SimpleNamespace(video_id="vid")

        def corpus(*builds, list_only=False, strict=False):
            self.loads.append((builds, list_only, strict))
            return [SimpleNamespace(timing=timed, units=frozenset())]

        v.app = SimpleNamespace(corpus=corpus)
        v._builds = lambda source: (source,)
        return v

    def test_the_corpus_is_loaded_once_for_both(self) -> None:
        v = self.viewer()
        held = v.corpus_for("subtitle", False)
        grouped = v._grouped("subtitle")
        self.assertEqual(len(self.loads), 1, "the reel loaded the corpus again")
        # Not merely equal: the same objects, or it is a second copy in memory.
        self.assertIs(grouped["vid"][0], held[0])

    def test_the_reel_first_still_only_loads_once(self) -> None:
        v = self.viewer()
        v._grouped("subtitle")
        v.corpus_for("subtitle", False)
        self.assertEqual(len(self.loads), 1)

    def test_it_asks_for_the_strict_corpus(self) -> None:
        """The reel counts every word in a line, which is what `strict` means
        — grouping the narrowed corpus would quietly change the score."""
        v = self.viewer()
        v._grouped("subtitle")
        self.assertEqual(self.loads[0], (("subtitle",), False, True))


class ForgetCorpusTest(unittest.TestCase):
    """Dropping the corpus has to drop what was read out of it.

    `_catch_up_now` analyses a newly scraped video and drops the corpus so
    the new lines are read. The grouping survived, so the reel went on
    showing the videos it knew before — the one just added was missing until
    the server restarted.
    """

    def test_everything_derived_goes_with_it(self) -> None:
        v = Viewer.__new__(Viewer)
        v._corpora, v._scopes = Once(), Once()
        v._videos = {"subtitle": {"vid": []}}
        v._video_levels = {"subtitle": ({}, None)}
        v._spoken = {"subtitle": {"vid": 9}}
        v._unit_videos = {"subtitle": {}}
        v._corpora.get("subtitle|all", lambda: ["a sentence"])
        v._forget_corpus()
        for name in ("_videos", "_video_levels", "_spoken", "_unit_videos"):
            self.assertEqual(getattr(v, name), {}, f"{name} outlived the corpus")
        self.assertNotIn("subtitle|all", v._corpora)


class RepairStoredScoresTest(unittest.TestCase):
    """`_rescore_locked`: keep the stored scores valid across a marked word."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scores = ScoreStore(Path(self.tmp.name) / "state.sqlite3")
        self.unit = Unit.lemma("haus")

    def viewer(self, *, ranked=False, corpus_loaded=False, stamp="fp|8|1"):
        v = Viewer.__new__(Viewer)
        v._corpora = Once()
        v._scores = self.scores
        v._ranked = {"subtitle": [row("a"), row("b")]} if ranked else {}
        v._videos = {"subtitle": {"a": [], "b": []}}
        v._unit_videos = {"subtitle": {}}
        v._spoken = {"subtitle": {}}
        v._video_levels = {"subtitle": ({}, None)}
        v._known = SimpleNamespace(units=frozenset())
        if corpus_loaded:
            v._corpora.get("subtitle|all", lambda: ["rows"])
        v.sources = lambda: {"subtitle": 10}
        v._score_stamp = lambda: stamp
        v.app = SimpleNamespace(goal_units=())
        v._score_video = lambda vid, *a, **k: row(vid, watch=9.0)
        self.scored = []
        return v

    def stored_stamp(self) -> str | None:
        return self.scores.stamp("subtitle")

    def test_a_word_no_video_says_only_moves_the_stamp(self) -> None:
        self.scores.save("subtitle", "fp|8|1", [row("a"), row("b")])
        v = self.viewer(corpus_loaded=True, stamp="fp|8|2")
        v._rescore_locked(self.unit)
        self.assertEqual(self.stored_stamp(), "fp|8|2")
        # Untouched, so the numbers must be exactly as they were.
        self.assertEqual([r["watch"] for r in self.scores.latest("subtitle")],
                         [1.0, 1.0])

    def test_the_videos_that_say_it_are_rescored_and_restamped(self) -> None:
        self.scores.save("subtitle", "fp|8|1", [row("a"), row("b")])
        v = self.viewer(corpus_loaded=True, stamp="fp|8|2")
        v._unit_videos["subtitle"] = {self.unit: {"a"}}
        v._rescore_locked(self.unit)
        self.assertEqual(self.stored_stamp(), "fp|8|2")
        got = {r["video"]: r["watch"] for r in self.scores.latest("subtitle")}
        self.assertEqual(got, {"a": 9.0, "b": 1.0})

    def test_it_repairs_with_no_ranking_in_memory(self) -> None:
        """The whole point: the word was marked from Next, not from the reel."""
        self.scores.save("subtitle", "fp|8|1", [row("a"), row("b")])
        v = self.viewer(ranked=False, corpus_loaded=True, stamp="fp|8|2")
        v._unit_videos["subtitle"] = {self.unit: {"a"}}
        self.assertEqual(v._ranked, {})
        v._rescore_locked(self.unit)
        self.assertEqual(self.stored_stamp(), "fp|8|2")
        self.assertEqual(v._ranked, {}, "rows read off disk leaked into memory")

    def test_a_process_with_neither_leaves_it_alone(self) -> None:
        """The MCP server marks words, holds no ranking and no corpus. It
        must not pay for one to update a page it never serves."""
        self.scores.save("subtitle", "fp|8|1", [row("a")])
        v = self.viewer(ranked=False, corpus_loaded=False, stamp="fp|8|2")
        v._videos = {}                       # nothing grouped either
        v._grouped = lambda s: self.fail("the corpus was materialised")
        v._rescore_locked(self.unit)
        self.assertEqual(self.stored_stamp(), "fp|8|1", "the stamp moved anyway")

    def test_a_rebuilt_corpus_is_not_papered_over(self) -> None:
        """Only a marked word may be repaired. If the analyser fingerprint or
        the scoring version has moved, every stored row was computed by rules
        that no longer apply — restamping would call them all fresh."""
        self.scores.save("subtitle", "old|8|1", [row("a"), row("b")])
        v = self.viewer(corpus_loaded=True, stamp="new|8|2")
        v._unit_videos["subtitle"] = {self.unit: {"a"}}
        v._rescore_locked(self.unit)
        self.assertEqual(self.stored_stamp(), "old|8|1",
                         "stale rows were declared fresh")

    def test_a_bumped_score_version_is_not_papered_over_either(self) -> None:
        self.scores.save("subtitle", "fp|7|1", [row("a")])
        v = self.viewer(corpus_loaded=True, stamp="fp|8|1")
        v._unit_videos["subtitle"] = {self.unit: {"a"}}
        v._rescore_locked(self.unit)
        self.assertEqual(self.stored_stamp(), "fp|7|1")

    def test_a_source_never_scored_is_skipped(self) -> None:
        v = self.viewer(corpus_loaded=True, stamp="fp|8|2")
        v._rescore_locked(self.unit)
        self.assertIsNone(self.stored_stamp())


if __name__ == "__main__":
    unittest.main()
