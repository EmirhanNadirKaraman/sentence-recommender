"""Study-list keys as something a voice can say.

The list writes for a matcher, and 72% of the plan's steps are patterns, so
reading keys out verbatim mangles most of the deck: `jdm. (Dat) passieren`
becomes letters and a spoken case label. These pin the shapes that were
actually wrong when the rule was first written -- every one of them came from
running it over the real 3,861 keys and reading what came out.
"""
from __future__ import annotations

import unittest

from deck.spoken import spoken


class SpokenTest(unittest.TestCase):
    def test_a_noun_keeps_its_article(self) -> None:
        """`Zeit` alone throws away the gender, which is half of what the
        entry is there to teach."""
        self.assertEqual(spoken("die Zeit"), "die Zeit")

    def test_a_verb_frame_is_spoken_as_its_verb(self) -> None:
        """The frames were never chosen -- one blueprint per verb, from the
        dictionary, often a rare use. The goal is the verb (TODO #26)."""
        self.assertEqual(spoken("jdm. (Dat) passieren"), "passieren")
        self.assertEqual(spoken("jdm. (Dat) etw. (Akk) geben"), "geben")
        self.assertEqual(spoken("jdm. (Dat) stehen"), "stehen")
        self.assertEqual(spoken("nach etw. aussehen"), "aussehen")

    def test_a_reflexive_keeps_its_sich(self) -> None:
        """`sich erinnern` and `erinnern` are two words."""
        self.assertEqual(spoken("an jdn./etw. sich erinnern"), "sich erinnern")
        self.assertEqual(spoken("gegen jdn./etw. sich wehren"), "sich wehren")

    def test_two_frames_still_share_one_verb(self) -> None:
        """Both branches name `sprechen`; the card is `sprechen`."""
        self.assertEqual(spoken("mit jdm. / über etw./jdn. sprechen"), "sprechen")
        self.assertEqual(spoken("auf etw. / an etw. ankommen"), "ankommen")

    def test_a_reflexive_frame_with_alternatives_is_still_the_reflexive(self) -> None:
        self.assertEqual(spoken("auf/über etw. (Akk) sich freuen"), "sich freuen")
        self.assertEqual(spoken("für/wegen etw. (Gen) sich schämen"), "sich schämen")

    def test_a_frame_with_a_sense_hint_is_still_its_verb(self) -> None:
        self.assertEqual(spoken("etw. (Zeit) (Akk) verbringen"), "verbringen")
        self.assertEqual(spoken("in etw. (Akk/Dat) bohren"), "bohren")
        self.assertEqual(spoken("für/gegen jdn./etw. stimmen"), "stimmen")

    def test_a_comma_offers_one_word_twice(self) -> None:
        self.assertEqual(spoken("gern, gerne"), "gern")
        self.assertEqual(spoken("der Vorsitzende, die Vorsitzende"),
                         "der Vorsitzende")

    def test_a_noun_spelled_like_a_case_survives(self) -> None:
        """`das Gen` is a word, and only its brackets would have been one."""
        self.assertEqual(spoken("das Gen"), "das Gen")

    def test_an_idiom_naming_two_words_is_spoken_whole(self) -> None:
        """No single head to hang the frame on, so the branch holding the
        verb is read as it stands."""
        self.assertEqual(spoken("etw. (Akk) / sich lassen scheiden"),
                         "sich lassen scheiden")

    def test_a_plain_lemma_is_left_alone(self) -> None:
        self.assertEqual(spoken("genau"), "genau")

    def test_nothing_unspeakable_survives(self) -> None:
        """The guard the whole module exists for."""
        for key in ("jdn. (Akk) + Name (Akk) nennen",
                    "jdm. (Dat) jdn./etw. (Akk) / sich (Dat) etw. (Akk) vorstellen",
                    "etw. (Akk) aus/von etw. ableiten"):
            said = spoken(key)
            for junk in ("(", ")", "/", "jdm", "jdn", "etw.", "Akk", "Dat"):
                self.assertNotIn(junk, said, f"{key} -> {said}")


if __name__ == "__main__":
    unittest.main()
