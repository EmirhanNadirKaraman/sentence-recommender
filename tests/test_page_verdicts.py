"""Ranking reads one fresh verdict snapshot per page, not per example."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from corpus.sentence import Sentence
from vocab.entry import Unit
from web.handlers import Viewer
from tests import test_web


class PageVerdictsTest(unittest.TestCase):
    def test_anki_fallbacks_share_one_snapshot_and_keep_both_cards(self):
        fixture = test_web.AnkiExamplesTest()
        viewer = fixture.viewer([], {})
        one, two = Unit('lemma', 'geben'), Unit('lemma', 'nehmen')
        snapshot = {'a sentence': 0.4}
        viewer.app.verdicts = Mock(return_value=snapshot)
        with patch('web.handlers.ExampleIndex') as index:
            index.return_value.examples.return_value = []
            answer = viewer.anki_examples('subtitle', {one, two})
        self.assertEqual(set(answer), {one, two})
        viewer.app.verdicts.assert_called_once_with()
        self.assertEqual(index.return_value.examples.call_count, 2)
        for call in index.return_value.examples.call_args_list:
            self.assertIs(call.kwargs['verdicts'], snapshot)

    def test_frontier_reads_once_and_preserves_each_word(self):
        viewer = Viewer.__new__(Viewer)
        one, two = Unit('lemma', 'geben'), Unit('lemma', 'nehmen')
        rows = [Sentence('Ich gebe dir das Buch.', units=frozenset({one})),
                Sentence('Ich nehme mir eine Pause.', units=frozenset({two}))]
        viewer._known = SimpleNamespace(units=frozenset())
        label = 'subtitle:strict:goals'
        viewer._store = SimpleNamespace(sources=lambda: [label],
            load=lambda name: [SimpleNamespace(position=i+1, unit=u) for i, u in enumerate((one,two))])
        viewer._frontier_corpus = lambda *args: rows
        from threading import Lock
        viewer._frontier_lock = Lock()
        viewer._frontier_index = lambda *args: SimpleNamespace(
            candidates=lambda: {one:{0}, two:{1}}, unlocks=lambda u: 0, readable=0, known=set())
        viewer._link = lambda path, source='', **params: path
        viewer.is_starred = lambda text: False
        viewer._page = lambda title, body, *args: body
        viewer.app = SimpleNamespace(goal_units=(one,two),
            verdicts=Mock(return_value={}), with_english=lambda rows: rows,
            judged=SimpleNamespace(worth=lambda text, unit: 1),
            settings=SimpleNamespace(goal_words=Path('study_list.txt')))
        body = viewer.frontier({})
        self.assertIn('/unit/lemma/geben', body)
        self.assertIn('/unit/lemma/nehmen', body)
        viewer.app.verdicts.assert_called_once_with()
