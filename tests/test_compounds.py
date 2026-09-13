"""Compounds as an expansion of what is known, never a rewrite of a sentence.

German writes `Krankenhaus` as one word, so a reader who knows `krank` and
`Haus` still meets it as a word they have never seen. An earlier attempt
split the sentence instead -- `Krankenhaus` became two units -- which erased
the compound and so made it impossible to teach one directly, and every wrong
entry deleted a real word from the corpus.

Applying it to the known set instead is monotone in the safe direction: it
can only make sentences readable earlier. These tests pin that it adds, that
it never subtracts, and that a wrong entry cannot cost a goal.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from roadmap.index import CorpusIndex
from roadmap.known_set import KnownSet
from roadmap.reach import reachable
from vocab.compounds import CHECKED_TO_HERE, Compounds, read_pairs
from vocab.entry import Unit


@dataclass(frozen=True)
class _Sentence:
    units: frozenset


def s(*keys: str) -> _Sentence:
    return _Sentence(frozenset(Unit("lemma", k) for k in keys))


def u(key: str) -> Unit:
    return Unit("lemma", key)


def over(pairs, inventory):
    return Compounds.over([u(k) for k in inventory], pairs=pairs)


class ReadingTheFileTest(unittest.TestCase):
    def test_it_stops_at_the_marker(self) -> None:
        """Below the line is unchecked guessing, and a third of it is wrong.

        `hochzeit` splits perfectly into `hoch` and `zeit` and means wedding.
        """
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compounds.txt"
            path.write_text(
                "krankenhaus\tkrank haus\t# 310\n"
                f"{CHECKED_TO_HERE}\n"
                "hochzeit\thoch zeit\t# 90\n", encoding="utf-8")
            pairs = read_pairs(path)
        self.assertEqual(pairs, {"krankenhaus": ("krank", "haus")})

    def test_the_shipped_file_parses(self) -> None:
        pairs = read_pairs()
        self.assertTrue(pairs)
        for word, parts in pairs.items():
            self.assertGreaterEqual(len(parts), 2, word)


class ResolutionTest(unittest.TestCase):
    """The file is plain lowercase; the analyser is not."""

    def test_a_part_resolves_to_the_noun_when_both_cases_exist(self) -> None:
        """`mittagessen` is Mittag plus *Essen* the meal, not `essen` the verb.

        Capitals sort before lowercase in Python, so a `max()` over the forms
        picks the verb every time. This is the regression that catches it.
        """
        c = over({"mittagessen": ("mittag", "essen")},
                 ["mittagessen", "mittag", "essen", "Essen"])
        self.assertEqual(c.parts_of(u("mittagessen")),
                         (frozenset({u("mittag")}), frozenset({u("Essen")})))

    def test_a_part_with_one_case_keeps_it(self) -> None:
        c = over({"krankenhaus": ("krank", "haus")},
                 ["krankenhaus", "krank", "haus"])
        self.assertEqual(c.parts_of(u("krankenhaus")),
                         (frozenset({u("krank")}), frozenset({u("haus")})))

    def test_a_compound_the_corpus_never_says_is_dropped(self) -> None:
        c = over({"atombombe": ("atom", "bombe")}, ["atom", "bombe"])
        self.assertEqual(len(c), 0)

    def test_a_part_the_corpus_never_says_is_dropped(self) -> None:
        """It could never fire, and keeping it inflates the reported effect."""
        c = over({"wohnzimmer": ("wohn", "zimmer")}, ["wohnzimmer", "zimmer"])
        self.assertEqual(len(c), 0)


class GoalFormTest(unittest.TestCase):
    """One word, two units — the reason a part is a set.

    The study list writes `das Haus`, the analyser writes `haus`, and strict
    counting drops the bare form from every sentence as a duplicate of the
    goal that teaches it. Resolving to the bare lemma alone left 187 of 231
    parts unresolvable and granted two compounds where the file holds 183.
    """

    def test_the_goal_that_teaches_a_part_satisfies_it(self) -> None:
        c = Compounds.over(
            [u("krankenhaus"), u("krank")],
            pairs={"krankenhaus": ("krank", "haus")},
            covered_by={"haus": frozenset({Unit("pattern", "das Haus")})})
        self.assertEqual(len(c), 1)
        self.assertEqual(
            c.derivable({u("krank"), Unit("pattern", "das Haus")}),
            {u("krankenhaus")})

    def test_a_verb_frame_does_not_satisfy_a_noun_part(self) -> None:
        """`etw. (Akk) essen` is how to use the verb, not the meal.

        Both it and `das Essen` are pattern units, so the kind cannot
        separate them — only whether the key names the word and nothing else.
        """
        covered = {"essen": frozenset({Unit("pattern", "etw. (Akk) essen")})}
        c = Compounds.over([u("mittagessen"), u("mittag")],
                           pairs={"mittagessen": ("mittag", "essen")},
                           covered_by=covered)
        self.assertEqual(len(c), 0)

    def test_either_name_is_enough(self) -> None:
        c = Compounds.over(
            [u("krankenhaus"), u("krank"), u("haus")],
            pairs={"krankenhaus": ("krank", "haus")},
            covered_by={"haus": frozenset({Unit("pattern", "das Haus")})})
        for name in (u("haus"), Unit("pattern", "das Haus")):
            self.assertEqual(c.derivable({u("krank"), name}),
                             {u("krankenhaus")}, name)


class DerivationTest(unittest.TestCase):
    def test_both_parts_are_needed(self) -> None:
        c = over({"krankenhaus": ("krank", "haus")},
                 ["krankenhaus", "krank", "haus"])
        self.assertEqual(c.derivable({u("krank")}), set())
        self.assertEqual(c.derivable({u("krank"), u("haus")}),
                         {u("krankenhaus")})

    def test_it_chains(self) -> None:
        """A compound can be a part of another compound."""
        c = over({"krankenhaus": ("krank", "haus"),
                  "krankenhausarzt": ("krankenhaus", "arzt")},
                 ["krankenhaus", "krankenhausarzt", "krank", "haus", "arzt"])
        self.assertEqual(c.derivable({u("krank"), u("haus"), u("arzt")}),
                         {u("krankenhaus"), u("krankenhausarzt")})

    def test_what_is_already_known_is_not_reported_as_derived(self) -> None:
        c = over({"krankenhaus": ("krank", "haus")},
                 ["krankenhaus", "krank", "haus"])
        self.assertEqual(
            c.derivable({u("krank"), u("haus"), u("krankenhaus")}), set())


class IndexTest(unittest.TestCase):
    """The walk's seam."""

    def build(self, sentences, known, pairs):
        units = {unit for s_ in sentences for unit in s_.units}
        units |= {u(k) for k in known}
        units |= {u(k) for parts in pairs.values() for k in parts}
        return CorpusIndex(sentences, KnownSet({u(k) for k in known}),
                           Compounds.over(units, pairs=pairs))

    def test_a_compound_is_known_from_the_start_if_its_parts_are(self) -> None:
        index = self.build([s("ich", "krankenhaus")], ["ich", "krank", "haus"],
                           {"krankenhaus": ("krank", "haus")})
        self.assertIn(u("krankenhaus"), index.known)
        self.assertIn(u("krankenhaus"), index.granted)
        self.assertEqual(index.readable, 1)

    def test_learning_the_last_part_grants_the_compound(self) -> None:
        index = self.build([s("ich", "krankenhaus")], ["ich", "krank"],
                           {"krankenhaus": ("krank", "haus")})
        self.assertEqual(index.readable, 0)
        index.learn(u("haus"))
        self.assertIn(u("krankenhaus"), index.known)
        self.assertEqual(index.readable, 1)

    def test_a_granted_compound_moves_its_own_sentences(self) -> None:
        """The grant is only worth anything if its sentences move with it.

        This is what the queue in `learn` exists for: the compound's own
        positions need the same decrement pass the learned unit got.
        """
        index = self.build(
            [s("ich", "krankenhaus"), s("du", "krankenhaus")],
            ["ich", "du", "krank"], {"krankenhaus": ("krank", "haus")})
        index.learn(u("haus"))
        self.assertEqual(index.readable, 2)

    def test_the_chain_runs_out_rather_than_stopping_at_one(self) -> None:
        index = self.build(
            [s("ich", "krankenhausarzt")], ["ich", "krank", "arzt"],
            {"krankenhaus": ("krank", "haus"),
             "krankenhausarzt": ("krankenhaus", "arzt")})
        self.assertEqual(index.readable, 0)
        index.learn(u("haus"))
        self.assertEqual(index.readable, 1)

    def test_the_compound_stays_a_unit_the_walk_can_teach(self) -> None:
        """The whole point of not rewriting the sentence.

        With splitting, `krankenhaus` ceased to exist and could never be a
        roadmap step. Here it is still a candidate when its parts are unknown.
        """
        index = self.build([s("ich", "krankenhaus")], ["ich"],
                           {"krankenhaus": ("krank", "haus")})
        self.assertIn(u("krankenhaus"), index.candidates())
        index.learn(u("krankenhaus"))
        self.assertEqual(index.readable, 1)

    def test_counts_never_go_negative(self) -> None:
        index = self.build([s("krankenhaus", "krank", "haus")], [],
                           {"krankenhaus": ("krank", "haus")})
        index.learn(u("krank"))
        index.learn(u("haus"))
        self.assertEqual(index.unknown_count(0), 0)
        self.assertEqual(index.readable, 1)


class ReachTest(unittest.TestCase):
    """The page's seam, which shares none of the walk's bookkeeping."""

    def c(self, pairs, sentences):
        units = {unit for s_ in sentences for unit in s_.units}
        units |= {u(k) for parts in pairs.values() for k in parts}
        return Compounds.over(units, pairs=pairs)

    def test_a_goal_behind_a_compound_becomes_reachable(self) -> None:
        pairs = {"krankenhaus": ("krank", "haus")}
        sentences = [s("krankenhaus", "goal")]
        known = {u("krank"), u("haus")}
        self.assertIn(u("goal"), reachable(sentences, known, {u("goal")},
                                           compounds=self.c(pairs, sentences)))
        # and without the entry it is not, which is what makes this a change
        self.assertNotIn(u("goal"), reachable(sentences, known, {u("goal")},
                                              compounds=self.c({}, sentences)))

    def test_a_grant_does_not_spend_budget(self) -> None:
        """Grants happen inside `learn`; only a deliberate purchase is priced.

        `spam` is the one off-list word worth buying, and one is all the
        budget holds. If the grant of `krankenhaus` were charged to it too,
        there would be nothing left to buy `spam` with.
        """
        pairs = {"krankenhaus": ("krank", "haus")}
        sentences = [s("krankenhaus", "spam"), s("spam", "goal")]
        known = {u("krank"), u("haus")}
        got = reachable(sentences, known, {u("goal")}, budget=1,
                        compounds=self.c(pairs, sentences))
        self.assertIn(u("goal"), got)
        # Without the grant the same budget reaches nothing: the first
        # sentence has two unknowns, so no single word is ever buyable.
        self.assertNotIn(u("goal"), reachable(sentences, known, {u("goal")},
                                              budget=1,
                                              compounds=self.c({}, sentences)))

    def test_it_never_puts_a_goal_out_of_reach(self) -> None:
        """The safety property, stated over every entry in the real file.

        A wrong entry can only mean a compound known too early. It cannot
        remove a word from a sentence, so whatever was reachable stays so.
        """
        pairs = read_pairs()
        sentences = [s("krankenhaus", "goal"), s("ich", "weltkrieg"),
                     s("weltkrieg", "other")]
        known = {u("ich")}
        goals = {u("goal"), u("other")}
        plain = reachable(sentences, known, goals, budget=3,
                          compounds=self.c({}, sentences))
        with_compounds = reachable(sentences, known, goals, budget=3,
                                   compounds=self.c(pairs, sentences))
        self.assertTrue(plain <= with_compounds)


class PurchaseLogTest(unittest.TestCase):
    """What `--unblock` actually costs, word by word."""

    def test_it_reports_each_off_list_word_and_what_it_freed(self) -> None:
        sentences = [s("spam", "goal"), s("spam", "ich"),
                     s("egg", "ich"), s("egg", "other")]
        bought = []
        reachable(sentences, {u("ich")}, {u("goal"), u("other")}, budget=4,
                  on_buy=lambda unit, n, freed: bought.append((unit, n, freed)))
        words = {unit for unit, _, _ in bought}
        self.assertIn(u("spam"), words)
        self.assertIn(u("egg"), words)
        for unit, count, freed in bought:
            self.assertEqual(count, len(freed))
        self.assertEqual({g for _, _, freed in bought for g in freed},
                         {u("goal"), u("other")})


if __name__ == "__main__":
    unittest.main()
