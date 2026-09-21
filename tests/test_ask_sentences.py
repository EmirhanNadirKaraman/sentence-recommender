"""The corpus pass: one request per sentence, every question in it, the
answers read back as numbers in [0, 1]."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from commands.ask_sentences import _once, read, state_and_questions
from corpus.sentence import Sentence
from vocab.entry import Unit


class RequestTest(unittest.TestCase):
    def sentence(self) -> Sentence:
        geben = Unit.pattern("jdm. (Dat) etw. (Akk) geben")
        return Sentence(text="Ich gebe dir das Buch.",
                        units=frozenset({geben, Unit.exact("ich"), Unit.exact("buch")}),
                        surfaces=((geben, "gebe dir dir das Buch"),))

    def test_only_pattern_units_are_asked_about(self) -> None:
        state, asked, which = state_and_questions(self.sentence())
        self.assertEqual(list(state["units"]), ["u1"])
        self.assertEqual(which["u1"].key, "jdm. (Dat) etw. (Akk) geben")
        self.assertEqual(state["units"]["u1"]["spoken"], "geben")

    def test_the_surface_says_each_word_once(self) -> None:
        state, _, _ = state_and_questions(self.sentence())
        self.assertEqual(state["units"]["u1"]["surface"], "gebe dir das Buch")
        self.assertEqual(_once("tue mir mir an an 0:3."), "tue mir an 0:3.")

    def test_every_question_travels_in_one_request(self) -> None:
        _, asked, _ = state_and_questions(self.sentence())
        self.assertEqual(set(asked), {"stands_alone", "complete", "standard", "well_formed",
                                      "expression", "level", "plain:u1", "guessable:u1"})

    def test_a_skipped_question_is_not_asked(self) -> None:
        """Charged per question per request, so a budget is met by not asking."""
        _, asked, _ = state_and_questions(self.sentence(), frozenset({"guessable", "level"}))
        self.assertNotIn("guessable:u1", asked)
        self.assertNotIn("level", asked)
        self.assertIn("plain:u1", asked)


class ReadTest(unittest.TestCase):
    def test_each_kind_becomes_a_number_in_the_unit_interval(self) -> None:
        answers = {
            "complete": SimpleNamespace(type="noul", noul=0.93),
            "guessable:u1": SimpleNamespace(type="score", score=1.5, legend={0: "", 1: "", 2: ""}),
            "level": SimpleNamespace(type="choice", choice="A2",
                                     probabilities={"A1": 0.2, "A2": 0.6, "B1": 0.2,
                                                    "B2": 0.0, "C1": 0.0}),
        }
        response = SimpleNamespace(answers=answers)
        out = read(response, dict.fromkeys(answers))
        self.assertEqual(out["complete"], (0.93, None))
        self.assertEqual(out["guessable:u1"], (0.75, None))
        value, distribution = out["level"]
        self.assertAlmostEqual(value, 0.25)      # expected level 1.0 of 4
        self.assertEqual(distribution["A2"], 0.6)


if __name__ == "__main__":
    unittest.main()


class BestVideosTest(unittest.TestCase):
    """`--videos N`: the lines of the reel's best N videos, best first,
    the thin and the removed left out."""

    def test_the_lines_come_best_video_first(self) -> None:
        import tempfile
        from pathlib import Path
        from alignment.timing import Timing
        from commands.ask_sentences import _of_the_best_videos
        from scores import ScoreStore
        from config import Settings
        from context import Application
        with tempfile.TemporaryDirectory() as tmp:
            app = Application(Settings(state_path=Path(tmp) / "state.sqlite3"))
            row = lambda video, watch, lines=50: {
                "video": video, "title": "", "lines": lines, "minutes": 10.0,
                "comprehension": 0.9, "i+1": 1, "teaches": 1, "watch": watch, "next": []}
            ScoreStore(app.settings.state_path).save("all", "stamp", [
                row("best", 0.9), row("thin", 0.95, lines=5), row("next", 0.5)])
            lines = [Sentence("Zweitbestes Video, erste Zeile.", timing=Timing("next", 1.0, 2.0)),
                     Sentence("Bestes Video, zweite Zeile.", timing=Timing("best", 9.0, 10.0)),
                     Sentence("Bestes Video, erste Zeile.", timing=Timing("best", 1.0, 2.0)),
                     Sentence("Zu dünn.", timing=Timing("thin", 1.0, 2.0)),
                     Sentence("Nicht im Feed.", timing=Timing("other", 1.0, 2.0)),
                     Sentence("Ohne Video.")]
            self.assertEqual([s.text for s in _of_the_best_videos(app, lines, 2)],
                             ["Bestes Video, erste Zeile.", "Bestes Video, zweite Zeile.",
                              "Zweitbestes Video, erste Zeile."])
            self.assertEqual([s.text for s in _of_the_best_videos(app, lines, 1)],
                             ["Bestes Video, erste Zeile.", "Bestes Video, zweite Zeile."])
            # A sample a video, drawn before the answered are left out, so a
            # resumed run draws the same lines and asks only what is left.
            first = _of_the_best_videos(app, lines, None, per_video=1)
            self.assertEqual(len(first), 2)                # one a video, two videos
            again = _of_the_best_videos(app, lines, None, per_video=1,
                                        have=frozenset({first[0].text}))
            self.assertEqual([s.text for s in again], [first[1].text])

    def test_a_videos_sample_is_the_same_every_time(self) -> None:
        from corpus.levels import sample
        texts = [f"Zeile {n}." for n in range(100)]
        drawn = sample("video", texts, 30)
        self.assertEqual(len(drawn), 30)
        self.assertEqual(drawn, sample("video", reversed(texts), 30))
        self.assertNotEqual(drawn, sample("other", texts, 30))
        self.assertEqual(sample("video", texts[:10], 30), sorted(texts[:10]))


class ScoreStoreLevelTest(unittest.TestCase):
    def test_a_videos_level_is_stored_and_read_back_and_an_old_table_gains_it(self) -> None:
        import sqlite3
        import tempfile
        from pathlib import Path
        from scores import ScoreStore
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.sqlite3"
            with sqlite3.connect(path) as conn:      # a table from before the column
                conn.execute("CREATE TABLE video_score (source TEXT NOT NULL, video_id TEXT "
                             "NOT NULL, title TEXT, lines INTEGER NOT NULL, minutes REAL, "
                             "comprehension REAL NOT NULL, teachable INTEGER NOT NULL, "
                             "teaches INTEGER NOT NULL, watch REAL NOT NULL, "
                             "next_words TEXT NOT NULL DEFAULT '[]', "
                             "PRIMARY KEY (source, video_id))")
            store = ScoreStore(path)
            row = {"video": "v", "title": "", "lines": 50, "minutes": 10.0,
                   "comprehension": 0.5, "i+1": 1, "teaches": 1, "watch": 0.3,
                   "next": [], "level": 1.5}
            store.save("subtitle", "stamp", [row])
            (back,) = store.load("subtitle", "stamp")
            self.assertEqual(back["level"], 1.5)
            store.update("subtitle", "stamp", [{**row, "level": None, "watch": 0.2}])
            (back,) = store.latest("subtitle")
            self.assertIsNone(back["level"])
            self.assertEqual(back["watch"], 0.2)

