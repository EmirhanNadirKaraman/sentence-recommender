"""One word, one unit — and the word stays in the sentence.

Strict counting used to collapse `die Schule` and the bare `schule` by
*deleting* the bare form, on the sole evidence that the list taught that word
somewhere. Nothing asked whether the goal was anywhere near. `die Technologie`
is on the list, so `technologie` was struck out of every sentence in the
corpus — including the ones that never say the goal and never teach it. 31% of
sentences lost a word with nothing standing in, and 313 of 3,910 roadmap steps
offered a sentence holding a word the reader could not have learned.

Renaming collapses the same duplicate and leaves the word behind as the goal,
which is the half that makes it teachable. These tests pin both halves: the
merge still happens, and nothing disappears.
"""
from __future__ import annotations

import unittest

from context import Application
from vocab.aliases import Aliases, heads
from vocab.entry import Unit


def rule(*goals: Unit, strict: bool = True, list_only: bool = False):
    """`Application._unit_rule` over a made-up goal list."""
    stub = type("Stub", (), {"goal_units": goals, "aliases": Aliases(goals)})()
    return Application._unit_rule(stub, strict, list_only)


class HeadsTest(unittest.TestCase):
    def test_an_article_noun_names_its_noun(self) -> None:
        self.assertEqual(heads("die Schule"), {"Schule"})

    def test_a_frame_names_its_verb(self) -> None:
        self.assertEqual(heads("etw./jdn. (Akk) haben"), {"haben"})
        self.assertEqual(heads("jdm. (Dat) etw. (Akk) geben"), {"geben"})

    def test_a_preposition_is_frame_when_a_verb_is_there(self) -> None:
        """`für jdn./etw. sorgen` teaches `sorgen`, not `für`.

        39 verbs were left unnamed by the goal that teaches them while this
        was missing — `gelten`, `nennen`, `stimmen`, 7,150 uses between them.
        """
        self.assertEqual(heads("für jdn./etw. sorgen"), {"sorgen"})
        self.assertEqual(heads("für/gegen jdn./etw. stimmen"), {"stimmen"})

    def test_a_preposition_alone_names_itself(self) -> None:
        """Stripped only when something else is left to name. `für` is a goal
        in its own right, and a one-word key has nothing else in it."""
        self.assertEqual(heads("bis"), {"bis"})
        self.assertEqual(heads("gegenüber"), {"gegenüber"})

    def test_a_role_goes_with_its_case_marker(self) -> None:
        """`Name (Akk)` is a slot; `der Name` is a noun.

        Listing `Name` as a frame word cost the list its own word for "name",
        which is the same shape of bug in the other direction.
        """
        self.assertEqual(heads("jdn. (Akk) + Name (Akk) nennen"), {"nennen"})
        self.assertEqual(heads("der Name"), {"Name"})

    def test_a_gloss_in_parentheses_keeps_the_head(self) -> None:
        """Only the four case markers count as a role's case."""
        self.assertEqual(heads("das Gen"), {"Gen"})

    def test_comma_alternatives_are_taken_one_at_a_time(self) -> None:
        """The list writes the same word twice this way, and read as one key
        it would name two words and so name nothing."""
        self.assertEqual(heads("gern, gerne"), {"gern", "gerne"})

    def test_a_key_saying_its_head_twice_is_one_word(self) -> None:
        self.assertEqual(heads("aus etw. / etw. (Akk) bestehen bestehen"),
                         {"bestehen"})

    def test_a_phrase_names_neither_word(self) -> None:
        """`etw. (Akk) / sich lassen scheiden` is an idiom. Letting it stand
        in for `lassen` would hand a reader the verb on its strength."""
        self.assertEqual(heads("etw. (Akk) / sich lassen scheiden"), set())

    def test_a_construction_names_neither_word(self) -> None:
        """`es gibt` must not name `es`: under strict counting every pronoun
        in the corpus would be renamed to the construction's goal."""
        self.assertEqual(heads("es gibt"), set())


class AliasTest(unittest.TestCase):
    def test_a_bare_lemma_becomes_the_goal(self) -> None:
        al = Aliases([Unit.pattern("die Technologie")])
        self.assertEqual(al.of(Unit.exact("technologie")),
                         Unit.pattern("die Technologie"))

    def test_an_unknown_word_is_left_alone(self) -> None:
        al = Aliases([Unit.pattern("die Technologie")])
        stranger = Unit.exact("quatsch")
        self.assertIs(al.of(stranger), stranger)

    def test_written_case_wins_over_folded(self) -> None:
        """Lemma keys are lowercase except the nouns that share one with a
        verb, which keep a capital to say which they are. Folding first put
        `Treffen` back together with `treffen`."""
        al = Aliases([Unit.pattern("das Treffen"),
                      Unit.pattern("jdn. (Akk) / sich mit jdm. treffen")])
        self.assertEqual(al.of(Unit.exact("Treffen")),
                         Unit.pattern("das Treffen"))
        self.assertEqual(al.of(Unit.exact("treffen")),
                         Unit.pattern("jdn. (Akk) / sich mit jdm. treffen"))

    def test_a_word_two_goals_name_resolves_the_same_way_every_run(self) -> None:
        """`Band` is `das Band`, `der Band` and `die Band`; one has to win and
        nothing in the list says which, so the choice is at least stable."""
        goals = [Unit.pattern("das Band"), Unit.pattern("der Band"),
                 Unit.pattern("die Band")]
        first = Aliases(goals).of(Unit.exact("Band"))
        self.assertEqual(Aliases(reversed(goals)).of(Unit.exact("Band")), first)

    def test_a_multi_word_key_is_never_renamed(self) -> None:
        al = Aliases([Unit.pattern("die Technologie")])
        phrase = Unit.pattern("etw. (Akk) / sich lassen scheiden")
        self.assertIs(al.of(phrase), phrase)


class UnitRuleTest(unittest.TestCase):
    def test_one_word_arriving_twice_collapses(self) -> None:
        """The original purpose, and the easiest thing to lose in a rewrite."""
        goal = Unit.pattern("etw./jdn. (Akk) haben")
        resolve = rule(goal)
        said = {Unit.exact("haben"), goal}
        self.assertEqual({resolve(unit) for unit in said}, {goal})

    def test_a_covered_word_stays_in_the_sentence(self) -> None:
        """The bug. `die Technologie` is on the list, so `technologie` was
        deleted from every sentence — including the ones that never say the
        goal and so could never teach it."""
        goal = Unit.pattern("die Technologie")
        resolve = rule(goal)
        self.assertEqual(resolve(Unit.exact("technologie")), goal)

    def test_a_stranger_is_kept_as_itself(self) -> None:
        """Neither known nor on the list. It has to keep counting against the
        sentence, which is the whole difference between strict and list."""
        resolve = rule(Unit.pattern("die Technologie"))
        self.assertEqual(resolve(Unit.exact("quatsch")), Unit.exact("quatsch"))

    def test_strict_never_drops_anything(self) -> None:
        resolve = rule(Unit.pattern("die Technologie"))
        for word in ("technologie", "quatsch", "Verkehr"):
            self.assertIsNotNone(resolve(Unit.exact(word)), word)

    def test_list_only_still_drops_a_stranger(self) -> None:
        """It keeps only what the list names, unknowns included — which is
        what makes it the looser reading of the two."""
        goal = Unit.pattern("die Technologie")
        resolve = rule(goal, strict=False, list_only=True)
        self.assertEqual(resolve(goal), goal)
        self.assertIsNone(resolve(Unit.exact("quatsch")))

    def test_list_only_renames_before_it_drops(self) -> None:
        """A verb the list teaches as a pattern arrives as a bare lemma
        wherever the matcher declines the pattern — the perfect tense, since
        it stopped crediting `haben` to `hat gelesen`. Dropping the lemma for
        not being a goal would call that sentence readable to someone who has
        never learned `haben`."""
        goal = Unit.pattern("etw./jdn. (Akk) haben")
        resolve = rule(goal, strict=False, list_only=True)
        self.assertEqual(resolve(Unit.exact("haben")), goal)
        self.assertIsNone(resolve(Unit.exact("technologie")))

    def test_nothing_to_do_costs_nothing(self) -> None:
        self.assertIsNone(rule(strict=False, list_only=False))


if __name__ == "__main__":
    unittest.main()
