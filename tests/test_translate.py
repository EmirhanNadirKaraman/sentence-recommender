"""The bulk translation pass, and the store it shares with the gloss."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from commands.translate_sentences import ordered, parse
from deck import Card, Example
from deck.gloss import GLOSS_VERSION, GlossStore, missing

MODEL = "some/model"


class ParseTest(unittest.TestCase):
    BLOCK = ["Ich habe keine Zeit.", "Das ist gut.", "Wo bist du?"]

    def test_entries_are_matched_by_the_number_the_model_echoed(self) -> None:
        """Twenty sentences in, nineteen answers out: pairing by position
        would attach every answer after the gap to the wrong German."""
        reply = "3. Where are you?\n1. I have no time."
        self.assertEqual(parse(reply, self.BLOCK), {
            "Wo bist du?": "Where are you?",
            "Ich habe keine Zeit.": "I have no time.",
        })

    def test_a_number_that_was_never_asked_is_ignored(self) -> None:
        reply = ("7. Seven.\n0. Zero.\nx. X.\n2. That is good.\n"
                 "Here are the translations:")
        self.assertEqual(parse(reply, self.BLOCK), {"Das ist gut.": "That is good."})

    def test_the_german_handed_back_is_stored_as_nothing(self) -> None:
        """The prompt asks for exactly that when a line is not German, so it
        is an answer -- and one worth remembering, so it is not asked again."""
        reply = "2.   das  ist gut. \n1. Ich habe keine Zeit."
        self.assertEqual(parse(reply, self.BLOCK),
                         {"Das ist gut.": "", "Ich habe keine Zeit.": ""})

    def test_a_bracket_after_the_number_is_tolerated(self) -> None:
        self.assertEqual(parse("1) No time.", self.BLOCK),
                         {"Ich habe keine Zeit.": "No time."})


class OrderTest(unittest.TestCase):
    def test_what_a_card_shows_goes_first_and_the_overlay_last(self) -> None:
        pending = [("a", True), ("b", True), ("c", True), ("d", False),
                   ("e", True), ("f", False)]
        shown = {"c"}
        candidates = {"c", "e", "f"}
        # `f` is a candidate the walk weighed even though no build calls it
        # teachable any more; what the walk weighed outranks what it did not.
        self.assertEqual(ordered(pending, shown, candidates),
                         ["c", "e", "f", "a", "b", "d"])


def _store(tmp: str) -> GlossStore:
    return GlossStore(Path(tmp) / "state.sqlite3")


class StoreTest(unittest.TestCase):
    def test_a_bulk_translation_is_english_but_was_not_asked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            store.save_translations({"Satz eins.": "Sentence one."}, MODEL)
            store.save("lemma", "zwei", [("Satz zwei.", "Sentence two.",
                                          "zwei means two.")], MODEL)
            self.assertEqual(store.sentences(MODEL), {
                "Satz eins.": "Sentence one.", "Satz zwei.": "Sentence two."})
            self.assertEqual(store.asked(MODEL), {"Satz zwei."})

    def test_the_gloss_wins_whichever_lands_second(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            store.save("lemma", "eins", [("Satz.", "From the gloss.", "x")],
                       MODEL)
            store.save_translations({"Satz.": "From the bulk pass."}, MODEL)
            self.assertEqual(store.sentences(MODEL)["Satz."], "From the gloss.")

            store.save_translations({"Anderer.": "Bulk first."}, MODEL)
            store.save("lemma", "eins", [("Anderer.", "Gloss second.", "x")],
                       MODEL)
            self.assertEqual(store.sentences(MODEL)["Anderer."], "Gloss second.")
            self.assertEqual(store.asked(MODEL), {"Satz.", "Anderer."})

    def test_a_stale_gloss_row_is_replaced_by_the_bulk_pass(self) -> None:
        """Only a *current* gloss answer is protected. An older prompt's row
        would be asked again anyway, and another model's is not this
        model's answer at all."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.sqlite3"
            store = GlossStore(path)
            store.save("lemma", "x", [("Alt.", "Old.", "x")], "other/model")
            with sqlite3.connect(path) as conn:
                conn.execute("INSERT INTO sentence_english (text, english, "
                             "version, model, source) VALUES (?,?,?,?,'gloss')",
                             ("Älter.", "Older.", GLOSS_VERSION - 1, MODEL))
            store.save_translations({"Alt.": "New.", "Älter.": "Newer."}, MODEL)
            self.assertEqual(store.sentences(MODEL),
                             {"Alt.": "New.", "Älter.": "Newer."})

    def test_an_older_database_reads_its_rows_as_the_gloss(self) -> None:
        """Every row written before the column existed came from the gloss,
        which was the only thing writing here."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.sqlite3"
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE sentence_english (text TEXT PRIMARY "
                             "KEY, english TEXT NOT NULL, version INTEGER NOT "
                             "NULL DEFAULT 0, model TEXT NOT NULL DEFAULT '', "
                             "made_at TEXT NOT NULL DEFAULT '')")
                conn.execute("INSERT INTO sentence_english VALUES (?,?,?,?,?)",
                             ("Satz.", "Sentence.", GLOSS_VERSION, MODEL, ""))
            store = GlossStore(path)
            self.assertEqual(store.sentences(MODEL), {"Satz.": "Sentence."})
            self.assertEqual(store.asked(MODEL), {"Satz."})


class MissingTest(unittest.TestCase):
    def test_a_card_the_bulk_pass_covered_is_still_owed_a_gloss(self) -> None:
        """The bulk pass gives every sentence English and asks about no
        word. Judged by "has English somewhere", such a card would never
        be glossed at all; judged by what the gloss has seen, it is."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            store.save_translations({"Eins.": "One.", "Zwei.": "Two."}, MODEL)
            english = store.sentences(MODEL)
            card = Card(1, "eins", False,
                        (Example("Eins.", english["Eins."]),
                         Example("Zwei.", english["Zwei."])), None, 1)
            self.assertEqual(missing([card], store.asked(MODEL)), [card])

    def test_a_promoted_sentence_beside_glossed_ones_is_still_asked(self) -> None:
        """The case commit 45ef3bd fixed, kept fixed: two sentences the gloss
        answered and one it never saw -- even one the bulk pass gave
        English to -- is a card with a question left in it."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            store.save("lemma", "eins",
                       [("Eins.", "One.", "eins means one."),
                        ("Zwei.", "Two.", "eins means one.")], MODEL)
            store.save_translations({"Drei.": "Three."}, MODEL)
            senses, english = store.senses(MODEL), store.sentences(MODEL)
            card = Card(1, "eins", False, tuple(
                Example(t, english[t], senses.get(("lemma", "eins", t)))
                for t in ("Eins.", "Zwei.", "Drei.")), None, 1)
            self.assertEqual(missing([card], store.asked(MODEL)), [card])
            # And once the gloss has seen it, declining or not, it rests.
            store.save("lemma", "eins", [("Drei.", "Three.", None)], MODEL)
            self.assertEqual(missing([card], store.asked(MODEL)), [])


if __name__ == "__main__":
    unittest.main()
