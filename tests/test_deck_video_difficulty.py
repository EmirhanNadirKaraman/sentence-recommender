"""How hard the video around a sentence is, inside the deck ranking.

A sentence can be perfectly i+1 and sit in a video where every other line is
hopeless. Nothing in the ranking used to notice.

Comprehension is the obvious measure and a dead one: measured against the
current vocabulary more than half of all videos have not one fully readable
sentence, so it is zero for the median video and would sort nothing. Mean
unknown words per sentence separates them — of the 1,378 videos with no
readable sentence at all it still runs 2.38 to 9.04.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from roadmap.examples import gaps_by_video, rank
from vocab.entry import Unit


@dataclass(frozen=True)
class _Timing:
    video_id: str


@dataclass(frozen=True)
class _Sentence:
    text: str
    units: frozenset
    timing: _Timing | None = None
    translation: str | None = None


def s(text: str, *keys: str, video: str | None = None) -> _Sentence:
    return _Sentence(text, frozenset(Unit("lemma", k) for k in keys),
                     _Timing(video) if video else None)


def u(key: str) -> Unit:
    return Unit("lemma", key)


class GapsTest(unittest.TestCase):
    def test_it_is_the_mean_unknown_units_per_sentence(self) -> None:
        known = frozenset({u("ich")})
        rows = [s("a", "ich", "one", video="v"),
                s("b", "ich", "one", "two", "three", video="v")]
        self.assertAlmostEqual(gaps_by_video(rows, known)["v"], 2.0)

    def test_a_sentence_with_no_video_is_not_counted(self) -> None:
        known = frozenset({u("ich")})
        rows = [s("a", "ich", "one", video="v"), s("b", "ich", "x", "y", "z")]
        self.assertAlmostEqual(gaps_by_video(rows, known)["v"], 1.0)

    def test_a_video_nobody_said_anything_in_is_absent(self) -> None:
        self.assertEqual(gaps_by_video([], frozenset()), {})


class RankTest(unittest.TestCase):
    """The deck key, with quality held level so the new band is what decides."""

    KNOWN = frozenset({u("ich"), u("und")})
    TARGET = u("ziel")

    def best(self, rows, gaps=None):
        return sorted(rows, key=rank(self.TARGET, self.KNOWN,
                                     None, gaps))[0].text

    # The last key of all is the text itself, ascending, so `alpha` wins any
    # tie these two are left in. Putting it in the *harder* video is what
    # makes these tests mean something: the band has to overcome it.
    ALPHA = "Ich und das Ziel alpha."
    OMEGA = "Ich und das Ziel omega."

    def pair(self):
        return [s(self.ALPHA, "ich", "und", "ziel", video="hard"),
                s(self.OMEGA, "ich", "und", "ziel", video="easy")]

    def test_without_the_band_the_text_decides(self) -> None:
        """The baseline these rest on, pinned so they cannot pass by luck."""
        self.assertEqual(self.best(self.pair()), self.ALPHA)

    def test_the_easier_video_wins_a_tie(self) -> None:
        self.assertEqual(self.best(self.pair(), {"easy": 2.0, "hard": 8.0}),
                         self.OMEGA)

    def test_a_video_with_no_measurement_sorts_last(self) -> None:
        """Unknown is not easy, so it must not win by default.

        `omega` would win on the band if an absent video counted as zero, and
        loses on the text otherwise — so this is the one thing it can show.
        """
        rows = [s(self.ALPHA, "ich", "und", "ziel", video="measured"),
                s(self.OMEGA, "ich", "und", "ziel", video="never-seen")]
        self.assertEqual(self.best(rows, {"measured": 7.0}), self.ALPHA)

    def test_it_is_banded_to_whole_words(self) -> None:
        """A tenth of a word is not a difference anyone could act on.

        Within a band the keys below decide, which is the whole reason the
        band exists — a finer one would leave length nothing to do. Three
        tenths is ignored; a word and a third is not.
        """
        self.assertEqual(self.best(self.pair(), {"hard": 4.4, "easy": 4.1}),
                         self.ALPHA)
        self.assertEqual(self.best(self.pair(), {"hard": 5.4, "easy": 4.1}),
                         self.OMEGA)


class NotBeforeQualityTest(unittest.TestCase):
    """The placement, and the reason it is a tie-break rather than a key.

    Length was tried ahead of quality and bought a shorter video by giving up
    the sentence itself. This sits in the same slot for the same reason, and
    measured over 399 units it changed 13% of them while costing nothing at
    four decimal places.
    """

    def test_a_better_sentence_in_a_harder_video_still_wins(self) -> None:
        known = frozenset({u("ich"), u("und")})
        target = u("ziel")
        good = s("Ich und das Ziel sind hier.", "ich", "und", "ziel",
                 video="hard")
        poor = s("ziel", "ziel", video="easy")
        self.assertEqual(
            sorted([good, poor],
                   key=rank(target, known, None, {"easy": 1.0, "hard": 9.0})
                   )[0].text,
            "Ich und das Ziel sind hier.")

    def test_readability_still_comes_first_of_all(self) -> None:
        """An easy video cannot buy a sentence with another unknown in it."""
        known = frozenset({u("ich")})
        target = u("ziel")
        clean = s("Ich ziel.", "ich", "ziel", video="hard")
        extra = s("Ich ziel mehr.", "ich", "ziel", "mehr", video="easy")
        self.assertEqual(
            sorted([clean, extra],
                   key=rank(target, known, None, {"easy": 0.5, "hard": 9.0})
                   )[0].text,
            "Ich ziel.")


if __name__ == "__main__":
    unittest.main()
