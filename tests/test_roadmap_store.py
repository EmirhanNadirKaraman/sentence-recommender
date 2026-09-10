"""What the roadmap writes down, and what it promises about it.

The stored roadmap is the whole of what the reading page shows: the step, the
deck of sentences that teach it, the video each came from.  Nothing loads the
corpus to check any of it, so a deck that comes back subtly wrong — a lost
surface, a unit set that no longer says what else is new — is wrong on the
page with nothing to catch it.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from alignment.timing import Timing
from corpus.sentence import Sentence
from roadmap.examples import DECK_SIZE, rank
from roadmap.index import CorpusIndex
from roadmap.known_set import KnownSet
from roadmap.priority import UnitPriority
from roadmap.refresh import read_label
from roadmap.builder import RoadmapBuilder
from roadmap.step import RoadmapStep
from roadmap.store import RoadmapStore
from vocab.entry import Unit

HAUS = Unit.lemma("haus")


def sentence(text: str, *keys: str, surface: str = "", video: str = "") -> Sentence:
    made = Sentence(text=text).with_units(
        frozenset(Unit.lemma(k) for k in keys),
        ((Unit.lemma(keys[0]), surface),) if surface and keys else (),
    )
    return made.with_timing(Timing(video, 12.5, 15.0)) if video else made


def step(position: int = 1, *examples: Sentence) -> RoadmapStep:
    return RoadmapStep(
        position=position,
        unit=HAUS,
        sentence=examples[0] if examples else sentence("x", "haus"),
        gain=3,
        score=4.5,
        now_readable=2,
        examples=examples,
        readable=1234,
        occurrences=56,
    )


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "state.sqlite3"
        self.store = RoadmapStore(self.path)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_a_deck_survives_the_round_trip(self) -> None:
        deck = (sentence("Das Haus ist gross.", "haus", "sein",
                         surface="Haus", video="abc123"),
                sentence("Ein Haus.", "haus"))
        self.store.save([step(1, *deck)], "src")

        loaded = self.store.load("src")
        back = self.store.deck("src", loaded[0])

        self.assertEqual([s.text for s in back], [s.text for s in deck])
        self.assertEqual(back[0].units, deck[0].units)
        self.assertEqual(back[0].surface_of(HAUS), "Haus")
        self.assertEqual(back[0].timing.video_id, "abc123")
        self.assertEqual(back[0].timing.start, 12.5)
        # A sentence never aligned to a video keeps saying so, rather than
        # coming back with a timing pointing at nothing.
        self.assertIsNone(back[1].timing)

    def test_the_counts_the_page_states_are_stored(self) -> None:
        self.store.save([step(1, sentence("a", "haus"))], "src")
        loaded = self.store.load("src")[0]
        self.assertEqual(loaded.readable, 1234)
        self.assertEqual(loaded.occurrences, 56)

    def test_loading_the_plan_does_not_drag_the_decks_along(self) -> None:
        """The roadmap page wants one line per step and none of the sentences."""
        self.store.save([step(1, sentence("a", "haus"))], "src")
        self.assertEqual(self.store.load("src")[0].examples, ())

    def test_saving_again_leaves_no_orphaned_deck(self) -> None:
        self.store.save([step(1, sentence("old", "haus"))], "src")
        self.store.save([step(1, sentence("new", "haus"))], "src")

        loaded = self.store.load("src")
        self.assertEqual([s.text for s in self.store.deck("src", loaded[0])],
                         ["new"])

    def test_a_deck_is_filed_per_source(self) -> None:
        self.store.save([step(1, sentence("subtitle one", "haus"))], "a")
        self.store.save([step(1, sentence("other one", "haus"))], "b")
        first = self.store.load("a")[0]
        self.assertEqual([s.text for s in self.store.deck("a", first)],
                         ["subtitle one"])

    def test_a_stamp_is_recorded_and_read_back(self) -> None:
        self.store.save([step(1)], "src", "fingerprint|1|3")
        self.assertEqual(self.store.stamp("src"), "fingerprint|1|3")

    def test_an_unstamped_roadmap_says_so(self) -> None:
        """Rather than claiming a stamp it cannot vouch for."""
        self.store.save([step(1)], "src")
        self.assertIsNone(self.store.stamp("src"))

    def test_appending_moves_the_stamp_to_what_extended_it(self) -> None:
        self.store.save([step(1)], "src", "first")
        self.store.append([step(2)], "src", "second")
        self.assertEqual(self.store.stamp("src"), "second")
        self.assertEqual(len(self.store.load("src")), 2)


class MigrationTest(unittest.TestCase):
    """A database written before the decks existed has to keep working.

    `CREATE TABLE IF NOT EXISTS` does nothing to a table that is already
    there, so the columns added since have to be put in by hand — this is the
    bug that bit the score cache, where a missing column failed on first write
    rather than on open.
    """

    def test_an_older_roadmap_gains_the_columns_it_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.sqlite3"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE roadmap (
                    source TEXT NOT NULL DEFAULT 'all', position INTEGER NOT NULL,
                    kind TEXT NOT NULL, key TEXT NOT NULL, sentence TEXT NOT NULL,
                    translation TEXT, origin TEXT NOT NULL, surface TEXT,
                    gain INTEGER NOT NULL, score REAL NOT NULL,
                    now_readable INTEGER NOT NULL, PRIMARY KEY (source, position));
                INSERT INTO roadmap VALUES
                    ('src', 1, 'lemma', 'haus', 'Ein Haus.', NULL, 'subtitle',
                     'Haus', 3, 4.5, 2);
            """)
            conn.commit()
            conn.close()

            store = RoadmapStore(path)
            loaded = store.load("src")

            self.assertEqual(len(loaded), 1)
            # The old row is honest about having recorded nothing.
            self.assertEqual(loaded[0].readable, 0)
            self.assertEqual(loaded[0].occurrences, 0)
            self.assertEqual(store.deck("src", loaded[0]), [])
            # And it can still be written to.
            store.append([step(2, sentence("Zwei.", "haus"))], "src")
            self.assertEqual(len(store.load("src")), 2)


class RankingTest(unittest.TestCase):
    def test_a_readable_sentence_beats_a_better_one_that_is_not(self) -> None:
        known = frozenset({Unit.lemma("sein")})
        readable = sentence("Das Haus ist gross und alt und schoen und weiss.",
                            "haus", "sein")
        better_but_harder = sentence(
            "Das Haus dort ist wirklich sehr gross und auch ziemlich alt.",
            "haus", "sein", "dort")
        self.assertEqual(
            sorted([better_but_harder, readable], key=rank(HAUS, known))[0],
            readable)

    def test_quality_breaks_the_tie_rather_than_shortness(self) -> None:
        """The bug this ranking was rewritten for.

        With no translations in a subtitle corpus the second key never fires,
        so ranking on length meant "the shortest readable sentence" — which
        for a pattern in two thousand sentences is a five-word fragment.
        """
        known: frozenset[Unit] = frozenset()
        short = sentence("Wo ist das Haus?", "haus")
        full = sentence("Das Haus am Ende der Strasse steht schon lange leer.",
                        "haus")
        self.assertEqual(sorted([short, full], key=rank(HAUS, known))[0], full)


class WalkDeckTest(unittest.TestCase):
    def test_the_walk_writes_a_deck_with_every_step(self) -> None:
        sentences = [sentence(f"Das Haus Nummer {n} steht an der Strasse.",
                              "haus", "sein") for n in range(30)]
        index = CorpusIndex(sentences, KnownSet({Unit.lemma("sein")}))
        steps = RoadmapBuilder(index, UnitPriority({})).build()

        self.assertTrue(steps)
        first = steps[0]
        self.assertEqual(first.unit, HAUS)
        # Capped, so a unit in thousands of sentences does not store them all.
        self.assertEqual(len(first.examples), DECK_SIZE)
        self.assertEqual(first.occurrences, 30)

    def test_a_deck_reaches_past_the_strictly_i_plus_one_sentences(self) -> None:
        """A deck of one cannot be stepped through.

        `Haus` is the only unknown in one sentence and shares the rest with
        `baum`, so the walk has a single i+1 sentence to teach it from — the
        deck still has to offer somewhere to go next.
        """
        sentences = [
            sentence("Das Haus ist gross.", "haus", "sein"),
            sentence("Das Haus und der Baum.", "haus", "baum"),
            sentence("Das Haus, der Baum, das Auto.", "haus", "baum", "auto"),
        ]
        index = CorpusIndex(sentences, KnownSet({Unit.lemma("sein")}))
        step_ = RoadmapBuilder(index, UnitPriority({})).peek()

        self.assertEqual(step_.unit, HAUS)
        self.assertEqual(len(step_.examples), 3)
        # Readable first, then by how much else is new in them.
        self.assertEqual(step_.examples[0].text, "Das Haus ist gross.")
        self.assertEqual(step_.examples[2].text, "Das Haus, der Baum, das Auto.")


class VideoFitTest(unittest.TestCase):
    """Which video a sentence is opened in, when the sentences tie.

    The reading page was landing eighty minutes into feature films, because
    the ranking had no opinion about video at all — it ordered sentences and
    took whatever clip the winner happened to sit in.
    """

    def deck(self, minutes):
        long_one = sentence("Alles, was du tust, geht mir auf die Nerven.",
                            "haus", video="long")
        short_one = sentence("Alles, was du tust, geht mir auf die Ohren.",
                             "haus", video="short")
        return sorted([long_one, short_one],
                      key=rank(HAUS, frozenset(), minutes))

    def test_a_shorter_video_wins_a_tie(self) -> None:
        first = self.deck({"long": 200.0, "short": 11.0})[0]
        self.assertEqual(first.timing.video_id, "short")

    def test_without_lengths_the_order_is_unchanged(self) -> None:
        """No durations to hand must rank exactly as it did before."""
        self.assertEqual([s.timing.video_id for s in self.deck(None)],
                         [s.timing.video_id for s in sorted(
                             self.deck(None), key=rank(HAUS, frozenset()))])

    def test_length_does_not_outrank_quality(self) -> None:
        """A good sentence in a long video beats a poor one in a short video.

        The tie-break is worth almost as much as sorting on length outright
        and costs no quality, which is the only reason it sits below it.
        """
        good_long = sentence("Alles, was du tust, geht mir auf die Nerven.",
                             "haus", video="long")
        poor_short = sentence("Na?", "haus", video="short")
        first = sorted([poor_short, good_long],
                       key=rank(HAUS, frozenset(), {"long": 200.0,
                                                    "short": 11.0}))[0]
        self.assertEqual(first.timing.video_id, "long")


class StrictWalkTest(unittest.TestCase):
    """Strict counting leaves words the list will never teach in the corpus.

    Narrowing removed them, which is why the walk never had to think about
    them. Now they sit on the frontier looking exactly like a goal, and the
    only thing keeping the roadmap on the study list is the walk refusing
    them by name.
    """

    def setUp(self) -> None:
        # `klausur` is a stranger: not known, not a goal, never taught.
        self.sentences = [
            sentence("Das Haus ist gross.", "haus", "sein"),
            sentence("Die Klausur war schwer.", "klausur", "sein"),
            sentence("Das Haus und die Klausur.", "haus", "klausur"),
        ]
        self.known = KnownSet({Unit.lemma("sein")})
        self.goals = frozenset({HAUS})

    def test_the_walk_refuses_a_word_that_is_not_a_goal(self) -> None:
        index = CorpusIndex(self.sentences, self.known)
        steps = RoadmapBuilder(index, UnitPriority({}), goals=self.goals,
                               only_goals=True).build()

        self.assertEqual([s.unit for s in steps], [HAUS])

    def test_without_the_refusal_it_teaches_the_stranger(self) -> None:
        """The same corpus, the same goals — only the refusal differs."""
        index = CorpusIndex(self.sentences, self.known)
        steps = RoadmapBuilder(index, UnitPriority({}), goals=self.goals).build()

        self.assertIn(Unit.lemma("klausur"), {s.unit for s in steps})

    def test_a_sentence_holding_a_stranger_is_never_offered(self) -> None:
        """The whole point: every other word in the sentence is known."""
        index = CorpusIndex(self.sentences, self.known)
        step = RoadmapBuilder(index, UnitPriority({}), goals=self.goals,
                              only_goals=True).peek()

        self.assertEqual(step.unit, HAUS)
        for example in step.examples:
            self.assertEqual(example.units - {HAUS} - self.known.units,
                             frozenset())


class LabelTest(unittest.TestCase):
    """A roadmap's name is the only record of the settings that built it.

    Reading it back wrongly fails silently: the corpus name comes out as a
    build that does not exist, `corpus()` returns nothing, and the refresh
    skips that roadmap without saying so.
    """

    def test_every_flag_is_read_back_off_the_end(self) -> None:
        self.assertEqual(read_label("subtitle:good:list:goals"),
                         (("subtitle",), True, True, True, False))

    def test_the_quality_flag_does_not_end_up_in_the_corpus_name(self) -> None:
        """`subtitle:good` is not a build, and asking for it loads nothing."""
        plan = read_label("subtitle:good:list:goals")
        self.assertEqual(plan.builds, ("subtitle",))
        self.assertTrue(plan.quality_only)

    def test_a_plain_roadmap_carries_no_flags(self) -> None:
        self.assertEqual(read_label("subtitle"),
                         (("subtitle",), False, False, False, False))
        self.assertEqual(read_label("all"), ((), False, False, False, False))

    def test_the_flags_are_independent(self) -> None:
        self.assertEqual(read_label("subtitle:list"),
                         (("subtitle",), True, False, False, False))
        self.assertEqual(read_label("subtitle:good"),
                         (("subtitle",), False, False, True, False))

    def test_strict_is_read_and_does_not_narrow(self) -> None:
        """The two are alternatives: strict counts every word in a sentence,
        narrowing counts only the ones on the list."""
        plan = read_label("subtitle:good:strict:goals")
        self.assertEqual(plan.builds, ("subtitle",))
        self.assertTrue(plan.strict)
        self.assertTrue(plan.quality_only)
        self.assertFalse(plan.list_only)


if __name__ == "__main__":
    unittest.main()
