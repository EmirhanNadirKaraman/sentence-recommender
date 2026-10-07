"""Literal i+1 evidence and minimum video count, independent of the UI."""
from collections import Counter
from types import SimpleNamespace
from unittest import mock
import json
import unittest

from alignment.timing import Timing
from corpus.sentence import Sentence
from roadmap.cover import minimum_subset
from vocab.entry import Unit
from vocab.search import UnitSearch
from web.handlers import Viewer


def u(key):
    return Unit('lemma', key)


def line(video, *words, at=1):
    return Sentence(' '.join(words), units=frozenset(map(u, words)),
                    timing=Timing(video, at, at + 2))


class MinimumSubsetTest(unittest.TestCase):
    def test_count_wins_over_minutes(self):
        rows = [line('long', 'a'), line('long', 'b'),
                line('short-a', 'a'), line('short-b', 'b')]
        cover, examples = minimum_subset(rows, frozenset(), frozenset({u('a'), u('b')}),
                                        {'long':100, 'short-a':1, 'short-b':1})
        self.assertEqual(cover.videos, ('long',))
        self.assertEqual(cover.status, 'Optimal')
        self.assertEqual(len(examples), 2)

    def test_shorter_duration_breaks_equal_count_ties(self):
        cover, _ = minimum_subset([line('long','a'), line('short','a')], frozenset(),
                                  frozenset({u('a')}), {'long':10, 'short':1})
        self.assertEqual(cover.videos, ('short',))

    def test_goals_do_not_unlock_each_other(self):
        rows = [line('a','a','known'), line('both','a','b')]
        cover, witnesses = minimum_subset(rows, frozenset({u('known')}),
                                          frozenset({u('a'),u('b')}), {'a':1,'both':1})
        self.assertEqual(cover.videos, ('a',))
        self.assertEqual(cover.unreachable, (u('b'),))
        for (_, unit), row in witnesses.items():
            self.assertEqual(row.units - {u('known')}, {unit})

    def test_unselected_unknowns_still_block_a_sentence(self):
        cover, _ = minimum_subset([line('v','target','stranger')], frozenset(),
                                  frozenset({u('target')}), {'v':1})
        self.assertFalse(cover.videos)
        self.assertEqual(cover.unreachable, (u('target'),))

    def test_short_clips_are_allowed_but_untimed_lines_are_not(self):
        rows = [line('clip','target'), Sentence('missing', units=frozenset({u('missing')}))]
        cover, _ = minimum_subset(rows, frozenset(), frozenset({u('target'),u('missing')}), {'clip':.1})
        self.assertEqual(cover.videos, ('clip',))
        self.assertEqual(cover.unreachable, (u('missing'),))

    def test_known_targets_are_not_misrepresented_as_i_plus_one(self):
        cover, _ = minimum_subset([line('v','a')], frozenset({u('a')}), frozenset({u('a')}), {'v':1})
        self.assertFalse(cover.taught)


class CoverInputTest(unittest.TestCase):
    def viewer(self):
        viewer = Viewer.__new__(Viewer)
        viewer._lists = SimpleNamespace(names=lambda:[('existing',2,'now')], save=mock.Mock())
        viewer.source = lambda query:'subtitle'
        viewer._cover_search = lambda source:UnitSearch(Counter({('lemma','a'):1}))
        return viewer

    def test_arbitrary_or_malformed_units_cannot_be_saved(self):
        for selected in ('{}','[{}]', '[{"kind":"lemma","key":"not-in-corpus"}]',
                         '[{"kind":[],"key":"a"}]'):
            viewer=self.viewer()
            self.assertIn('error', viewer.cover_json({'name':'new','selected':selected}))
            viewer._lists.save.assert_not_called()

    def test_new_draft_cannot_silently_overwrite_an_existing_collection(self):
        viewer=self.viewer()
        answer=viewer.cover_json({'name':'existing','selected':json.dumps([{'kind':'lemma','key':'a'}])})
        self.assertIn('error', answer)
        viewer._lists.save.assert_not_called()

    def test_empty_and_over_limit_drafts_are_rejected(self):
        for selected in ([], [{'kind':'lemma','key':'a'}]*101):
            viewer=self.viewer()
            self.assertIn('error',viewer.cover_json({'name':'new','selected':json.dumps(selected)}))
            viewer._lists.save.assert_not_called()

    def test_normalized_search_validates_the_same_unit_as_the_corpus(self):
        canonical=Unit('pattern','das Haus')
        search=UnitSearch(Counter({('lemma','haus'):8,('pattern','das Haus'):3}),
                          rename=lambda unit:canonical)
        [(unit, count, _)]=search.find('haus')
        self.assertEqual((unit,count),(canonical,11))
        self.assertTrue(search.contains(canonical))
        self.assertEqual(search.exact('das Haus'),canonical)

class CoverIntegrationTest(unittest.TestCase):
    def test_saved_list_cover_and_witnesses_agree_and_are_reader_local(self):
        from tests import pg
        from vocab.word_lists import WordListStore
        from roadmap.cover import VideoCoverStore
        one, two = pg.schema(self), pg.schema(self)
        viewer=Viewer.__new__(Viewer)
        viewer.app=SimpleNamespace(settings=SimpleNamespace(state=one, own=one))
        viewer._lists=WordListStore(one)
        viewer._known=SimpleNamespace(units=frozenset({u('known')}))
        viewer.source=lambda query:'subtitle'
        viewer._cover_search=lambda source:UnitSearch(Counter({('lemma',k):1 for k in ('a','b','blocked','known')}))
        viewer.app.corpus=lambda *sources,**kwargs:[line('both','a','known',at=10),
                                                  line('both','b','known',at=20),
                                                  line('wrong','blocked','stranger')]
        viewer._minutes=lambda:{'both':12,'wrong':1}
        viewer._corpus_stamp=lambda:'now'
        viewer.list_name=lambda:'study_list'
        fake=mock.MagicMock()
        fake.__enter__.return_value.rows.return_value=[('both','Two useful words')]
        with mock.patch('web.handlers.Database',return_value=fake):
            answer=viewer.cover_json({'name':'personal','selected':json.dumps([
                {'kind':'lemma','key':k} for k in ('a','b','blocked','known')])})
        self.assertNotIn('error',answer)
        self.assertTrue(answer['optimal'])
        self.assertEqual((answer['covered'],answer['total']),(2,4))
        self.assertEqual(answer['unreachable'],['blocked'])
        self.assertEqual(answer['known'],['known'])
        self.assertEqual(viewer._lists.entries('personal'),('a','b','blocked','known'))
        self.assertEqual(WordListStore(two).entries('personal'),())
        self.assertEqual(VideoCoverStore(one).videos('personal','subtitle:minimum-count'),('both',))
        self.assertEqual([e['word'] for e in answer['videos'][0]['examples']],['a','b'])
        self.assertIn('t=10',answer['videos'][0]['examples'][0]['url'])

class TargetedCorpusReadTest(unittest.TestCase):
    def test_multi_target_read_filters_sentences_but_preserves_other_unknowns(self):
        from tests import pg
        from state import ensure, open_state
        from corpus.store import CorpusStore
        config=pg.schema(self)
        ensure(config, '''
            CREATE TABLE corpus_sentence (id BIGINT PRIMARY KEY, build TEXT, origin TEXT,
                text TEXT, translation TEXT, raw_text TEXT, source_ids TEXT,
                video_id TEXT, start_time DOUBLE PRECISION, end_time DOUBLE PRECISION,
                teachable BOOLEAN, language TEXT);
            CREATE TABLE corpus_unit (sentence_id BIGINT, kind TEXT, key TEXT, surface TEXT);
        ''')
        with open_state(config) as conn:
            for sid, text in ((1,'a stranger'),(2,'another'),(3,'phrase stranger')):
                conn.execute("INSERT INTO corpus_sentence VALUES (%s,'subtitle','subtitle',%s,NULL,NULL,'','v',1,3,true,'de')",(sid,text))
            conn.executemany('INSERT INTO corpus_unit VALUES (%s,%s,%s,%s)',[
                (1,'lemma','a','a'),(1,'lemma','stranger','stranger'),(2,'lemma','another','another'),
                (3,'pattern','phrase','phrase'),(3,'lemma','stranger','stranger')])
        store=CorpusStore(config)
        self.addCleanup(lambda:store._connection.close() if store._connection else None)
        goals=frozenset({u('a'),Unit('pattern','phrase')})
        rows=store.load('subtitle',holding_many=goals)
        self.assertEqual({row.text for row in rows},{'a stranger','phrase stranger'})
        self.assertTrue(all(u('stranger') in row.units for row in rows))
        cover,_=minimum_subset(rows,frozenset(),goals,{'v':1})
        self.assertEqual(set(cover.unreachable),set(goals))
        self.assertEqual(store.load('subtitle',holding_many=frozenset()),[])

class CoverTimestampTest(unittest.TestCase):
    def test_example_link_opens_at_its_sentence_without_loading_the_feed(self):
        viewer=Viewer.__new__(Viewer)
        viewer.source=lambda query:'subtitle'
        viewer._plan_walk=lambda query,source:''
        viewer._catalogue=lambda:[('v','A video',2)]
        viewer._cues=lambda video:[line('v','a',at=42.88)]
        viewer.app=SimpleNamespace(with_english=lambda rows:rows)
        viewer._known=SimpleNamespace(units=frozenset())
        viewer._watchable=mock.Mock(side_effect=AssertionError('must not load the whole feed'))
        viewer._wrote_it=lambda video:''
        viewer._taste_control=lambda video,here:''
        viewer._audio_toggle=lambda:''
        viewer._taught_here=lambda *args:''
        viewer._page=lambda title,body,path,source:body
        body=viewer.video_page({'id':'v','t':'42.88'})
        self.assertIn('chosen example starts at 0:42',body)
        self.assertIn('start=42',body)
        viewer._watchable.assert_not_called()
