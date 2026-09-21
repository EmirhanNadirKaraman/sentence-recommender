"""Fixed expressions are units of their own, found by their words.

`auf jeden Fall` is not `der Fall`, `tut mir leid` is not `tun`, and
`eine Rolle spielen` is not `spielen`: the matched words are consumed
where the corpus is analysed, exactly as `es gibt` consumes `geben`.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from corpus.analyzer import Evidence, UnitAnalyzer
from vocab.expressions import canonicals
from vocab.study_list import StudyListBuilder

try:
    import spacy
    spacy.util.get_package_path("de_core_news_md")
    _PARSER = True
except Exception:                                    # noqa: BLE001 — optional model
    _PARSER = False

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "matcher"))

REGISTERED = frozenset({"auf jeden Fall", "auf keinen Fall", "es tut mir leid",
                        "eine Rolle spielen", "zur Verfügung stehen", "davon ausgehen",
                        "der Fall", "etw. (Akk) spielen", "jdm. (Dat) stehen"})


class FileTest(unittest.TestCase):
    def test_the_file_is_read_two_ways(self) -> None:
        """The matcher reads how each is found; the rest reads the names,
        and a line naming a canonical with no pattern still names one."""
        import phrase_finder                              # noqa: PLC0415 — no parse needed for the loader
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "expressions.txt"
            path.write_text("# a comment\n\nes gibt\n"
                            "auf keinen Fall\tauf [gar] keinen fall\n"
                            "es tut mir leid\t[es] tut mir * leid\n"
                            "in den Griff bekommen\tbekommen/kriegen :: in den griff\n",
                            encoding="utf-8")
            self.assertEqual(canonicals(path), ("es gibt", "auf keinen Fall", "es tut mir leid",
                                                "in den Griff bekommen"))
            rows, by_verb = phrase_finder.load_expressions(path)
            self.assertEqual(rows, [("auf keinen Fall", [("auf", False), ("gar", True),
                                                          ("keinen", False), ("fall", False)]),
                                    ("es tut mir leid", [("es", True), ("tut", False), ("mir", False),
                                                         (None, True), ("leid", False)])])
            self.assertEqual(sorted(by_verb), ["bekommen", "kriegen"])
            self.assertEqual(by_verb["kriegen"], [("in den Griff bekommen",
                                                   [("in", False), ("den", False), ("griff", False)])])

    def test_the_study_list_carries_them_after_the_ranked_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "order.txt").write_text("haben\n", encoding="utf-8")
            (root / "forms.txt").write_text("haben\tetw./jdn. (Akk) haben\n", encoding="utf-8")
            (root / "expressions.txt").write_text("es gibt\nauf jeden Fall\tauf jeden fall\n",
                                                  encoding="utf-8")
            builder = StudyListBuilder(root / "order.txt", root / "forms.txt",
                                       root / "expressions.txt")
            builder.write(root / "study_list.txt")
            lines = [l for l in (root / "study_list.txt").read_text(encoding="utf-8").splitlines()
                     if l and not l.startswith("#")]
            self.assertEqual(lines, ["haben\tetw./jdn. (Akk) haben", "es gibt\tes gibt",
                                     "auf jeden Fall\tauf jeden Fall"])
            # Generated, so not a hand edit: a rebuild does not refuse.
            self.assertEqual(builder.hand_edits(root / "study_list.txt"), [])


@unittest.skipUnless(_PARSER, "de_core_news_md is not installed")
class MatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.analyzer = UnitAnalyzer(REGISTERED)

    def units(self, text: str) -> set[str]:
        doc = self.analyzer.matcher.nlp(text)
        found, _ = self.analyzer._units(doc, Evidence())
        return {str(u) for u in found}

    def test_words_in_a_row_are_the_unit_and_nothing_else(self) -> None:
        found = self.units("Das ist auf jeden Fall richtig.")
        self.assertIn("pattern:auf jeden Fall", found)
        self.assertNotIn("pattern:der Fall", found)
        self.assertNotIn("lemma:Fall", found)
        self.assertIn("lemma:richtig", found)

    def test_an_optional_word_and_a_wildcard(self) -> None:
        self.assertIn("pattern:auf keinen Fall", self.units("Auf gar keinen Fall!"))
        found = self.units("Es tut mir wirklich leid.")
        self.assertIn("pattern:es tut mir leid", found)
        self.assertNotIn("lemma:tun", found)
        # `wirklich` is a word the sentence says, around the expression.
        self.assertIn("lemma:wirklich", found)

    def test_words_hanging_from_the_verb_replace_its_frame(self) -> None:
        found = self.units("Auch religiöse Motive spielen dabei eine große Rolle.")
        self.assertIn("pattern:eine Rolle spielen", found)
        self.assertNotIn("pattern:etw. (Akk) spielen", found)
        self.assertNotIn("lemma:spielen", found)
        self.assertNotIn("lemma:Rolle", found)
        # The object's adjective is not the expression's word.
        self.assertIn("lemma:groß", found)

    def test_the_verb_keeps_its_frame_where_the_words_are_not_its(self) -> None:
        found = self.units("Die Kinder spielen draußen.")
        self.assertIn("pattern:etw. (Akk) spielen", found)
        self.assertNotIn("pattern:eine Rolle spielen", found)

    def test_a_separated_prefix_is_part_of_the_verb(self) -> None:
        found = self.units("Ich gehe davon aus, dass er kommt.")
        self.assertIn("pattern:davon ausgehen", found)
        self.assertNotIn("lemma:ausgehen", found)
        self.assertNotIn("lemma:davon", found)


@unittest.skipUnless(_PARSER, "de_core_news_md is not installed")
class ParallelTest(unittest.TestCase):
    def test_the_pool_gives_the_analysers_own_answer(self) -> None:
        """Eight workers, the same units and surfaces as one process — the
        first pass is per sentence, and the vote the second pass reads is
        merged from every worker's tally."""
        from corpus import parallel
        from corpus.sentence import Sentence
        texts = ["Das ist auf jeden Fall richtig.", "Es gibt ein Problem.",
                 "Ich habe die Prüfung bestanden.", "Er steht früh auf."] * 3
        sentences = [Sentence(t) for t in texts]
        analyzer = UnitAnalyzer(REGISTERED | {"es gibt"})
        serial = analyzer.analyze_all(sentences)
        parallel.CHUNK, chunk = 4, parallel.CHUNK
        try:
            pooled = parallel.analyze_all(analyzer, sentences, 2)
        finally:
            parallel.CHUNK = chunk
        self.assertEqual([(s.units, s.surfaces) for s in pooled],
                         [(s.units, s.surfaces) for s in serial])


if __name__ == "__main__":
    unittest.main()
