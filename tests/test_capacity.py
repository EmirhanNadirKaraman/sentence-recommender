"""Regression proof for sharing data without sharing learning progress."""
from concurrent.futures import ThreadPoolExecutor
import gc
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace
import weakref

from corpus.shared import CorpusPool, CorpusRows
from corpus.sentence import Sentence
from roadmap.examples import ExampleIndex
from roadmap.index import CorpusIndex
from roadmap.known_set import KnownSet
from vocab.entry import Unit
from web.handlers import Scope, Viewer
from tests.test_design import Links


def test_concurrent_readers_load_once_and_unused_data_can_be_released():
    pool, barrier, guard = CorpusPool(), Barrier(4), Lock()
    loads = []
    def make():
        with guard:
            loads.append(1)
        return [Sentence('A sentence')]
    def load(_):
        barrier.wait()
        return pool.get(('de', 'v1'), make)
    with ThreadPoolExecutor(max_workers=4) as threads:
        rows = list(threads.map(load, range(4)))
    assert len(loads) == 1
    assert all(row is rows[0] for row in rows)
    assert pool.get(('de', 'v2'), make) is not rows[0]
    reference = weakref.ref(rows[0])
    del rows
    gc.collect()
    assert reference() is None


def test_shared_indexes_preserve_progress_and_example_order():
    a, b, absent = (Unit('lemma', word) for word in ('a', 'b', 'absent'))
    rows = CorpusRows([Sentence('A', units=frozenset({a})),
                       Sentence('AB', units=frozenset({a, b})),
                       Sentence('B', units=frozenset({b}))])
    left = CorpusIndex(rows, KnownSet())
    right = CorpusIndex(rows, KnownSet({a, absent}))
    reference = CorpusIndex(list(rows), KnownSet({a, absent}))
    assert left._sentence_units is right._sentence_units
    assert left._by_unit is right._by_unit
    left.learn(a)
    assert left.readable == right.readable == reference.readable
    assert right.candidates() == reference.candidates()
    right.learn(b)
    reference.learn(b)
    assert right.readable == reference.readable == 3
    assert b not in left.known
    assert absent not in left.known
    assert left.readable == 1
    examples, other = ExampleIndex(rows), ExampleIndex(rows)
    assert examples._by_unit is other._by_unit
    assert examples._by_unit[a] == (rows[0], rows[1])


def test_next_proposal_reused_until_learning_filters_or_verdicts_change():
    unit = Unit('lemma', 'a')
    index = SimpleNamespace(known=frozenset(), readable=0)
    calls = []
    def peek(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(unit=unit)
    scope = Scope([Sentence('A')], index, SimpleNamespace(peek=peek),
                  SimpleNamespace(examples=lambda *a, **k: ['A'], count=lambda u: 1), None)
    judge = object()
    def reading(skip=frozenset(), kinds=frozenset(), known=frozenset(), verdicts=None):
        return scope.reading(skip, kinds, known, verdicts or {}, judge)
    assert reading() is reading()
    assert len(calls) == 1
    index.known = frozenset({unit})
    reading(known=index.known)
    reading(skip=frozenset({unit}))
    reading(kinds=frozenset({'lemma'}))
    reading(verdicts={'A': False})
    assert len(calls) == 5
    index.known = frozenset()  # undo/rebuilt index
    reading()
    assert len(calls) == 6
    from roadmap.examples import read_vectors_from, forget_vectors
    state = SimpleNamespace  # hashable sentinel, no database read by this fake
    read_vectors_from(state)
    try:
        reading()
        assert len(calls) == 7
    finally:
        forget_vectors(state)


def test_catalogue_pages_are_bounded_and_keep_filters_and_all_videos():
    viewer = Viewer.__new__(Viewer)
    viewer.app = SimpleNamespace(settings=SimpleNamespace(goal_words=Path('travel.txt')))
    viewer.source = lambda query: 'subtitle'
    viewer.ordering = lambda query: 'watch'
    viewer._plan_for = lambda *args: {}
    rows = [dict(video=f'video{i:06}', title='Conversation', comprehension=.8,
                 level=1., watch=.7, teaches=12, lines=100, minutes=8, **{'i+1': 30})
            for i in range(55)]
    viewer._watchable = lambda *args, **kwargs: rows
    viewer._wrote_it = viewer._order_switch = viewer._add_video_form = lambda *args: ''
    viewer._page = lambda title, body, *args: body
    visited = []
    for page, count in ((1, 24), (2, 24), (3, 7)):
        html = viewer.subtitles({'page': str(page), 'q': 'Conversation'})
        tiles = [a for a in Links(html).links if a.get('class') == 'video-tile']
        assert len(tiles) == count
        assert html.count('<tr>') == count + 1
        from urllib.parse import parse_qs, urlsplit
        for tile in tiles:
            query = parse_qs(urlsplit(tile['href']).query)
            assert query['list'] == ['travel']
            visited.extend(query['id'])
        for link in Links(html).links:
            query = parse_qs(urlsplit(link['href']).query)
            if 'page' in query:
                assert query['q'] == ['Conversation']
                assert query['list'] == ['travel']
                assert query['sort'] == ['watch']
    assert visited == [row['video'] for row in rows]
    assert viewer.subtitles({'page': 'bad'}).count("class='video-tile'") == 24


def test_corpus_views_keep_reader_corrections_and_version_separate(monkeypatch):
    from context import Application
    from vocab.aliases import Aliases
    pool, loaded = CorpusPool(), []
    a, b = Unit('lemma', 'a'), Unit('lemma', 'b')
    source = [Sentence('A', units=frozenset({a})), Sentence('B', units=frozenset({b}))]
    def make():
        app = Application.__new__(Application)
        app.corpus_pool = pool
        app.settings = SimpleNamespace(own='database', language='de', state='state')
        app.check_freshness = lambda: None
        app.goal_units = (a,)
        app.aliases = Aliases(app.goal_units, 'de')
        app._hidden, app._fixes, app._doubts = set(), {}, {}
        app.overrides = SimpleNamespace(hidden=lambda: app._hidden,
                                        corrected=lambda: app._fixes)
        app.judged = SimpleNamespace(doubted=lambda: app._doubts)
        app.banned_videos = lambda: frozenset()
        app._version = 'v1'
        def load(*args, **kwargs):
            loaded.append(1)
            return list(source)
        app.corpus_store = SimpleNamespace(load=load, builds=lambda: ['subtitle'],
                                           vintage=lambda: app._version)
        return app
    monkeypatch.setattr('roadmap.examples.read_vectors_from', lambda state: None)
    left, right = make(), make()
    first, second = left.corpus('subtitle'), right.corpus('subtitle')
    assert first is second
    assert len(loaded) == 1
    right._hidden = {'A'}
    hidden = right.corpus('subtitle')
    assert [row.text for row in hidden] == ['B']
    assert [row.text for row in first] == ['A', 'B']
    assert hidden.base is first
    right._hidden = set()
    right._fixes = {'A': {b: 'A'}}
    fixed = right.corpus('subtitle')
    assert fixed[0].units == frozenset({b})
    assert first[0].units == frozenset({a})
    right._fixes = {}
    right._version = 'v2'
    assert right.corpus('subtitle') is not first
    assert len(loaded) == 2


def test_reverse_video_index_is_shared_and_immutable():
    from alignment.timing import Timing
    import pytest
    a = Unit('lemma', 'a')
    rows = CorpusRows([Sentence('A', units=frozenset({a}), timing=Timing('video', 0, 1)),
                       Sentence('no video', units=frozenset({a}))])
    groups, units = rows.videos()
    assert rows.videos() == (groups, units)
    assert rows.videos()[0] is groups
    assert groups['video'] == (rows[0],)
    assert units[a] == frozenset({'video'})
    with pytest.raises(TypeError):
        groups['other'] = ()


def test_shared_frontiers_match_direct_sentence_counts_after_each_learning_step():
    from vocab.compounds import Compounds
    units = [Unit('lemma', f'word{i}') for i in range(8)]
    rows = CorpusRows([Sentence(f'Line {i}', units=frozenset(
        units[j] for j in range(8) if (i + j * j) % (j + 2) == 0)) for i in range(100)])
    for seed in ([], units[:2], units[::2]):
        index = CorpusIndex(rows, KnownSet(seed), Compounds())
        known = set(seed)
        for unit in units:
            index.learn(unit)
            known.add(unit)
            candidates = {}
            readable = 0
            for pos, row in enumerate(rows):
                unknown = row.units - known
                if not unknown:
                    readable += 1
                elif len(unknown) == 1:
                    candidates.setdefault(next(iter(unknown)), set()).add(pos)
            assert index.readable == readable
            assert index.candidates() == candidates
