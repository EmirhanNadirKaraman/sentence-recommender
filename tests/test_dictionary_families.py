"""Dictionary duplicates collapse visually, without granting grammar knowledge."""
import unittest
from types import SimpleNamespace

from corpus.store import CorpusStore
from state import ensure, open_state
from tests import pg
from vocab.entry import Unit
from vocab.search import word_families
from web.handlers import Viewer


class FamilyTest(unittest.TestCase):
    def test_screenshot_verbs_have_one_row_each(self):
        units = [Unit('lemma', word) for word in ('aufgeben', 'angeben')]
        units += [Unit('pattern', 'etw. (Akk) ' + word) for word in ('aufgeben', 'angeben')]
        families = word_families(units)
        self.assertEqual(len(families), 2)
        self.assertTrue(all(len(members) == 2 for members in families.values()))
        self.assertEqual(families, word_families(reversed(units)))

    def test_multiword_and_english_phrasal_verbs_stay_separate(self):
        for language, keys in [('de', ('geben', 'es gibt')), ('en', ('give', 'give up'))]:
            units = [Unit('lemma', keys[0]), Unit('pattern', keys[1])]
            self.assertEqual(len(word_families(units, language)), 2)

    def test_noun_and_verb_case_stays_distinct(self):
        noun, verb = Unit('lemma', 'Treffen'), Unit('lemma', 'treffen')
        meeting = Unit('pattern', 'das Treffen')
        meet = Unit('pattern', 'sich mit jdm. treffen')
        self.assertEqual(word_families([noun, verb, meeting, meet]),
                         {noun: (noun, meeting), verb: (verb, meet)})

    def test_render_keeps_pattern_actions_and_knowledge_separate(self):
        bare = Unit('lemma', 'angeben')
        pattern = Unit('pattern', 'etw. (Akk) angeben')
        viewer = Viewer.__new__(Viewer)
        viewer.source = lambda query: 'subtitle'
        viewer._units_like = lambda *args: {bare: 200, pattern: 195}
        viewer._builds = lambda source: ('subtitle',)
        viewer._known = SimpleNamespace(units=frozenset({bare}))
        viewer._goal_set = lambda: frozenset({bare})
        viewer._page = lambda title, body, *args: body
        viewer.anki_button = lambda u, hidden: f'<form>{hidden}<button>Anki</button></form>'
        viewer.app = SimpleNamespace(
            settings=SimpleNamespace(language='de'),
            analyzer=SimpleNamespace(verb_lemmas={}),
            corpus_store=SimpleNamespace(family_counts=lambda *args: {bare: 203}))
        body = viewer.word_search({'q': 'angeben'})
        self.assertEqual(body.count('<tr>'), 2)  # heading plus one word
        self.assertIn("<details class='word-usages'>", body)
        self.assertIn('/unit/pattern/etw.', body)
        self.assertIn("value='etw. (Akk) angeben'", body)
        self.assertIn("<td class='n'>203</td>", body)
        self.assertEqual(body.count("class='tag'>known"), 1)


class FamilyCountsTest(unittest.TestCase):
    def test_union_counts_shared_lines_once_and_respects_source(self):
        config = pg.schema(self)
        ensure(config, '''
            CREATE TABLE corpus_sentence (id BIGINT PRIMARY KEY, build TEXT);
            CREATE TABLE corpus_unit (sentence_id BIGINT, kind TEXT, key TEXT);
        ''')
        bare = Unit('lemma', 'angeben')
        pattern = Unit('pattern', 'etw. (Akk) angeben')
        with open_state(config) as conn:
            conn.executemany('INSERT INTO corpus_sentence VALUES (%s,%s)',
                             [(1, 'subtitle'), (2, 'subtitle'), (3, 'subtitle'), (4, 'generated')])
            conn.executemany('INSERT INTO corpus_unit VALUES (%s,%s,%s)',
                             [(1, bare.kind, bare.key), (1, bare.kind, bare.key),
                              (1, pattern.kind, pattern.key), (2, bare.kind, bare.key),
                              (3, pattern.kind, pattern.key), (4, pattern.kind, pattern.key)])
        store = CorpusStore(config)
        self.addCleanup(lambda: store._connection.close() if store._connection else None)
        self.assertEqual(store.family_counts({bare: (bare, pattern)}, 'subtitle'), {bare: 3})
        self.assertEqual(store.family_counts({bare: (bare, pattern)}), {bare: 4})
        self.assertEqual(store.family_counts({}, 'subtitle'), {})
