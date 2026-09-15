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

    def test_a_role_is_written_out(self) -> None:
        self.assertEqual(spoken("jdm. (Dat) passieren"), "jemandem passieren")
        self.assertEqual(spoken("jdm. (Dat) etw. (Akk) geben"),
                         "jemandem etwas geben")

    def test_the_frame_is_kept(self) -> None:
        """`nach etwas aussehen` teaches the preposition the verb takes,
        which is the thing a learner actually gets wrong."""
        self.assertEqual(spoken("nach etw. aussehen"), "nach etwas aussehen")

    def test_one_slot_takes_the_first_filler(self) -> None:
        self.assertEqual(spoken("etw./jdn. (Akk) lassen"), "etwas lassen")

    def test_alternatives_without_dots_collapse_too(self) -> None:
        """`auf/über` has no abbreviating period, so a rule written for
        `etw./jdn.` walked straight past it and left a slash in the speech."""
        self.assertEqual(spoken("für/gegen jdn./etw. stimmen"),
                         "für jemanden stimmen")

    def test_two_frames_share_their_verb(self) -> None:
        """Splitting on ` / ` and keeping the first branch loses the verb:
        it sits at the end of the last branch, not the first."""
        self.assertEqual(spoken("mit jdm. / über etw./jdn. sprechen"),
                         "mit jemandem sprechen")
        self.assertEqual(spoken("auf etw. / an etw. ankommen"),
                         "auf etwas ankommen")

    def test_the_reflexive_moves_to_the_front(self) -> None:
        """The list writes the slots in order; nobody speaks them that way."""
        self.assertEqual(spoken("auf/über etw. (Akk) sich freuen"),
                         "sich auf etwas freuen")
        self.assertEqual(spoken("für/wegen etw. (Gen) sich schämen"),
                         "sich für etwas schämen")

    def test_a_comma_offers_one_word_twice(self) -> None:
        self.assertEqual(spoken("gern, gerne"), "gern")
        self.assertEqual(spoken("der Vorsitzende, die Vorsitzende"),
                         "der Vorsitzende")

    def test_every_bracket_is_annotation(self) -> None:
        """A case, a sense hint, or a pair of cases — none of it is speech."""
        self.assertEqual(spoken("etw. (Zeit) (Akk) verbringen"),
                         "etwas verbringen")
        self.assertEqual(spoken("in etw. (Akk/Dat) bohren"), "in etwas bohren")

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
