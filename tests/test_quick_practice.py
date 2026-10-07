"""No-plan guest lessons stay bounded without hiding unknown words."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from corpus.sentence import Sentence
from roadmap.priority import UnitPriority
from vocab.entry import Unit
from web.handlers import Once, Viewer


class QuickPracticeTest(unittest.TestCase):
    def test_bounded_scope_reuses_rows_and_keeps_genuine_unknowns(self):
        known, target, other = (Unit('lemma', word) for word in ('ich', 'pause', 'fremd'))
        rows = [Sentence('Ich Pause.', units=frozenset({known, target})),
                Sentence('Ich Pause fremd.', units=frozenset({known, target, other}))]
        viewer = Viewer.__new__(Viewer)
        viewer._known = SimpleNamespace(units=frozenset({known}))
        viewer._priority = UnitPriority.build([target])
        viewer._scopes = Once()
        viewer._corpus_at = None
        viewer._corpus_stamp = lambda: 'corpus-version'
        viewer.corpus_for = Mock(side_effect=AssertionError('full corpus must not load'))
        viewer.app = SimpleNamespace(corpus=Mock(return_value=rows), compounds=None,
            goal_units=frozenset({target}), settings=SimpleNamespace(priority_weight=0))
        scope = viewer.scope('subtitle', False, limit=2000)
        self.assertIs(scope, viewer.scope('subtitle', False, limit=2000))
        viewer.app.corpus.assert_called_once_with('subtitle', list_only=False, strict=True, limit=2000)
        self.assertEqual(scope.index.candidates()[target], {0})
        scope.index.learn(target)
        self.assertEqual(scope.index.candidates()[other], {1})
        self.assertEqual(viewer._corpus_at, 'corpus-version')
        viewer._scopes.clear()
        viewer.scope('subtitle', False, limit=2000)
        self.assertEqual(viewer.app.corpus.call_count, 2)

    def test_live_fallback_caps_guests_but_preserves_owner_scope(self):
        for guest in (None, object()):
            with self.subTest(guest=guest is not None):
                viewer = Viewer.__new__(Viewer)
                viewer.app = SimpleNamespace(guest=guest, snoozes=SimpleNamespace(asleep=lambda: frozenset()),
                    verdicts=lambda: {}, judged=None)
                viewer._known = SimpleNamespace(units=frozenset())
                viewer.scope = Mock()
                viewer._walked({}, 'subtitle', '')
                if guest is None:
                    viewer.scope.assert_called_once_with('subtitle', False)
                else:
                    viewer.scope.assert_called_once_with('subtitle', False, limit=2000)

    def test_valid_stored_plan_still_wins_over_live_fallback(self):
        viewer = Viewer.__new__(Viewer)
        step = SimpleNamespace(readable=7, occurrences=3)
        viewer._planned = Mock(return_value=(step, ['example'], 100))
        viewer._walked = Mock(side_effect=AssertionError('should use stored plan'))
        self.assertEqual(viewer.next_step({}, 'subtitle', ''), (step, ['example'], 7, 3, 100))
