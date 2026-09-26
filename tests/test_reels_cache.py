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
from threading import Lock
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

        v._corpus_at = None
        v.app = SimpleNamespace(
            corpus=corpus,
            corpus_store=SimpleNamespace(vintage=lambda: "T1"))
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
        v._corpus_at = "T1"
        v._corpora.get("subtitle|all", lambda: ["a sentence"])
        v._forget_corpus()
        for name in ("_videos", "_video_levels", "_spoken", "_unit_videos"):
            self.assertEqual(getattr(v, name), {}, f"{name} outlived the corpus")
        self.assertNotIn("subtitle|all", v._corpora)
        self.assertIsNone(v._corpus_at,
                          "a vintage naming a corpus no longer held")


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
        # `(basis, stamp)`: the basis is every field but the known-set
        # version, which is the one a marked word is allowed to move.
        v._score_stamps = lambda: (stamp.rsplit("|", 1)[0], stamp)
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

    def test_an_added_video_is_not_papered_over_either(self) -> None:
        """The one this field was added for. A video appended to a build moves
        no fingerprint and marks no word, so the stored rows are complete for
        a catalogue that no longer exists. Patching the word and restamping
        would carry that gap forward under every later known-version, which is
        exactly how one video stayed invisible for two days."""
        self.scores.save("subtitle", "fp|8|subtitle:T1|1", [row("a"), row("b")])
        v = self.viewer(corpus_loaded=True, stamp="fp|8|subtitle:T2|2")
        v._unit_videos["subtitle"] = {self.unit: {"a"}}
        v._rescore_locked(self.unit)
        self.assertEqual(self.stored_stamp(), "fp|8|subtitle:T1|1",
                         "rows with no row for the new video were called fresh")

    def test_only_the_known_version_moving_still_takes_the_cheap_path(self) -> None:
        """The incremental repair is the point of all this and must survive
        the field above: a marked word may still be patched in place."""
        self.scores.save("subtitle", "fp|8|subtitle:T1|1", [row("a"), row("b")])
        v = self.viewer(corpus_loaded=True, stamp="fp|8|subtitle:T1|2")
        v._unit_videos["subtitle"] = {self.unit: {"a"}}
        v._rescore_locked(self.unit)
        self.assertEqual(self.stored_stamp(), "fp|8|subtitle:T1|2")
        got = {r["video"]: r["watch"] for r in self.scores.latest("subtitle")}
        self.assertEqual(got, {"a": 9.0, "b": 1.0})


class CorpusMovedTest(unittest.TestCase):
    """`_corpus_moved`: a corpus written to from outside this process.

    `add-video` at the terminal appends to a build the running server is
    holding, and nothing in the server asked. The stamp covers the rows on
    disk; this covers the ones in memory — `_ranked` above all, which
    `_watchable` serves before it takes a lock or consults a stamp.

    The vintage compared is the one `corpus_for` recorded when it loaded, not
    one read at the moment of asking. Reading it here would find the corpus
    equal to itself while memory held an older one.
    """

    def viewer(self, written: str):
        v = Viewer.__new__(Viewer)
        self.written = written
        v._corpora = Once()
        v._scopes = Once()
        v._ranked = {"subtitle": [row("a")]}
        v._videos = {"subtitle": {"a": []}}
        v._video_levels = {"subtitle": ({}, None)}
        v._spoken = {"subtitle": {}}
        v._unit_videos = {"subtitle": {}}
        v._frontiers = {"x": []}
        v._frontier_at = {"x": (None, 0)}
        v._stuck = {"x": []}
        v._sources = {"subtitle": 10}
        v._listing = [("a", "A", 5.0)]
        v._corpus_at = None
        v._builds = lambda source: (source,)
        v.app = SimpleNamespace(
            corpus=lambda *b, **kw: ["a sentence"],
            corpus_store=SimpleNamespace(vintage=lambda: self.written))
        return v

    def test_nothing_loaded_means_nothing_to_forget(self) -> None:
        """A process that has read no corpus cannot be holding a stale one,
        whatever the builds say — and must not throw away a ranking it read
        off the disk to find that out."""
        v = self.viewer("T1")
        self.written = "T2"
        v._corpus_moved()
        self.assertIsNone(v._corpus_at)
        self.assertIn("subtitle", v._ranked, "a cold process threw away its work")

    def test_loading_records_the_corpus_it_read(self) -> None:
        v = self.viewer("T1")
        v.corpus_for("subtitle", False)
        self.assertEqual(v._corpus_at, "T1")

    def test_an_unchanged_corpus_keeps_the_ranking(self) -> None:
        v = self.viewer("T1")
        v.corpus_for("subtitle", False)
        v._corpus_moved()
        self.assertEqual(v._ranked, {"subtitle": [row("a")]})

    def test_a_written_corpus_drops_the_ranking_and_the_rest(self) -> None:
        v = self.viewer("T1")
        v.corpus_for("subtitle", False)
        self.written = "T2"                 # add-video, in another process
        v._corpus_moved()
        self.assertIsNone(v._corpus_at, "a vintage outlived the rows it named")
        for name in ("_ranked", "_videos", "_video_levels", "_spoken",
                     "_unit_videos", "_frontiers", "_frontier_at", "_stuck"):
            self.assertEqual(getattr(v, name), {}, f"{name} outlived the corpus")
        self.assertIsNone(v._sources)
        self.assertIsNone(v._listing)
        self.assertNotIn("subtitle|all", v._corpora)

    def test_a_later_load_does_not_overwrite_the_oldest(self) -> None:
        """`_corpus_at` names the oldest corpus in memory, so a mixture of
        vintages is thrown away rather than believed."""
        v = self.viewer("T1")
        v.corpus_for("subtitle", False)
        self.written = "T2"
        v.corpus_for("subtitle", True)     # a different key, a newer corpus
        self.assertEqual(v._corpus_at, "T1")


class ScoredUnderTest(unittest.TestCase):
    """What `_compute` stamps its rows with, and what `_watchable` keeps.

    The bug this guards: the corpus in memory is older than the one on disk,
    so the rows are missing a video — and stamping them with the live corpus
    says they are not. They then survive a restart as a cache hit.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scores = ScoreStore(Path(self.tmp.name) / "state.sqlite3")

    def viewer(self, written: str):
        v = Viewer.__new__(Viewer)
        self.written = written
        v._corpora = Once()
        v._scopes = Once()
        v._scores = self.scores
        v._ranked = {}
        v._scoring = Lock()
        v._videos = {}
        v._video_levels = {"subtitle": ({}, None)}
        v._spoken = {"subtitle": {}}
        v._unit_videos = {}
        v._frontiers = {}
        v._frontier_at = {}
        v._stuck = {}
        v._sources = None
        v._listing = None
        v._corpus_at = None
        v._known = SimpleNamespace(units=frozenset())
        v._builds = lambda source: (source,)
        v._score_video = lambda vid, *a, **k: row(vid, watch=9.0)
        v._taste = SimpleNamespace(all=lambda: {})
        v._channel_of = lambda: {}
        timed = SimpleNamespace(video_id="a")
        v.app = SimpleNamespace(
            goal_units=(),
            banned_videos=lambda: frozenset(),
            marked_known=SimpleNamespace(version=lambda: 1),
            corpus=lambda *b, **kw: [SimpleNamespace(timing=timed,
                                                     units=frozenset())],
            corpus_store=SimpleNamespace(vintage=lambda: self.written))
        return v

    def test_rows_are_stamped_with_the_corpus_they_were_read_from(self) -> None:
        v = self.viewer("T1")
        v.corpus_for("subtitle", False)     # the page before this one
        self.written = "T2"                 # add-video, mid-request
        rows, at = v._compute("subtitle")
        self.assertEqual(at, "T1")
        self.assertEqual(self.scores.stamp("subtitle").rsplit("|", 1)[0],
                         v._score_stamps("T1")[0],
                         "rows read from T1 were stamped with T2")
        self.assertEqual([r["video"] for r in rows], ["a"])

    def test_the_next_reader_of_those_rows_recomputes(self) -> None:
        """The proof that the stamp above is worth writing: a reader on the
        newer corpus must not be handed them."""
        v = self.viewer("T1")
        v.corpus_for("subtitle", False)
        self.written = "T2"
        v._compute("subtitle")
        fresh = self.viewer("T2")          # a restart, on the newer corpus
        _, stamp = fresh._score_stamps()
        self.assertIsNone(self.scores.load("subtitle", stamp),
                          "rows that never saw the new video were served")

    def test_a_ranking_is_not_put_back_after_the_corpus_moved(self) -> None:
        v = self.viewer("T1")
        v.corpus_for("subtitle", False)
        def compute(source):
            self.written = "T2"            # a build lands mid-pass
            v._forget_derived()            # as the catch-up thread would
            return [row("a")], "T1"
        v._compute = compute
        v._watchable("subtitle", floor=1)
        self.assertEqual(v._ranked, {}, "the cleared ranking was restored")


class ScoreBasisTest(unittest.TestCase):
    """The basis has to name the corpus, or none of the above can fire."""

    def viewer(self, written: str):
        v = Viewer.__new__(Viewer)
        self.written = written
        v.app = SimpleNamespace(
            corpus_store=SimpleNamespace(vintage=lambda: self.written),
            marked_known=SimpleNamespace(version=lambda: 7))
        return v

    def test_writing_a_build_moves_the_basis(self) -> None:
        v = self.viewer("T1")
        before, _ = v._score_stamps()
        self.written = "T2"
        after, stamp = v._score_stamps()
        self.assertNotEqual(before, after, "a new video left the basis unchanged")
        self.assertTrue(stamp.endswith("|7"), "the known version must stay last")
        self.assertEqual(stamp.rsplit("|", 1)[0], after)


if __name__ == "__main__":
    unittest.main()
