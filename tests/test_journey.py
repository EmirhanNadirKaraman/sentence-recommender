"""Rewards must represent real practice, survive reloads, and stay reader-owned."""
from datetime import datetime, timezone
import unittest
from journey import JourneyStore, level_for
from tests import pg


class JourneyTest(unittest.TestCase):
    def setUp(self):
        self.config = pg.schema(self, 'journey')
        self.store = JourneyStore(self.config)
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)

    def record(self, kind, entity):
        return self.store.record(kind, entity, now=self.now)

    def snapshot(self):
        return self.store.snapshot(now=self.now)

    def test_reload_is_not_activity_and_duplicate_words_do_not_award(self):
        self.assertEqual(self.snapshot()['xp'], 0)
        self.assertEqual(self.snapshot()['active_days'], 0)
        self.assertEqual(self.record('learn', 'lemma:pause'), 10)
        self.assertEqual(self.record('learn', 'lemma:pause'), 0)
        self.assertEqual(JourneyStore(self.config).snapshot(now=self.now)['xp'], 10)
        self.store.undo_word('lemma:pause')
        self.assertEqual(self.snapshot()['xp'], 0)
        self.assertEqual(self.record('learn', 'lemma:pause'), 10)
        self.assertEqual(self.snapshot()['xp'], 10)
        for _ in range(3):
            self.store.undo_word('lemma:pause')
            self.record('learn', 'lemma:pause')
        self.assertEqual(self.snapshot()['xp'], 10)

    def test_relearning_restores_original_day_without_filling_new_daily_quest(self):
        self.record('learn', 'lemma:pause')
        self.store.undo_word('lemma:pause')
        tomorrow = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
        self.store.record('learn', 'lemma:pause', now=tomorrow)
        data = self.store.snapshot(now=tomorrow)
        self.assertEqual(data['xp'], 10)
        self.assertEqual(data['today_xp'], 0)
        self.assertEqual(data['quests'][0]['value'], 0)

    def test_concurrent_listening_never_exceeds_daily_cap(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            points = list(pool.map(lambda i:self.record('listen', f'Line {i}'), range(28)))
        self.assertEqual(sum(points), 80)
        self.assertEqual(self.snapshot()['xp'], 80)
        with ThreadPoolExecutor(max_workers=4) as pool:
            data = list(pool.map(lambda _:self.snapshot(), range(4)))
        self.assertTrue(all(d['xp'] == 80 for d in data))
        self.assertTrue(all(next(b for b in d['badges'] if b['key'] == 'voice')['earned'] for d in data))

    def test_another_reader_cannot_receive_or_undo_my_rewards(self):
        other = JourneyStore(pg.schema(self, 'other_journey'))
        self.record('learn', 'lemma:pause')
        other.undo_word('lemma:pause')
        self.assertEqual(self.snapshot()['xp'], 10)
        self.assertEqual(other.snapshot(now=self.now)['xp'], 0)
        self.assertNotEqual(self.store.identity, other.identity)

    def test_listening_is_deduplicated_and_daily_reward_is_bounded(self):
        self.assertEqual(self.record('listen', 'A real sentence'), 4)
        self.assertEqual(self.record('listen', 'A real sentence'), 0)
        for i in range(25):
            self.record('listen', f'Line {i}')
        data = self.snapshot()
        self.assertEqual(data['xp'], 80)
        self.assertEqual(data['counts']['listen'], 20)
        self.assertEqual(data['quests'][2]['value'], 3)
        tomorrow = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
        self.assertEqual(self.store.record('listen', 'A real sentence', now=tomorrow), 4)

    def test_daily_chapter_bonus_is_once_and_requires_all_three_skills(self):
        for i in range(5):
            self.record('learn', f'lemma:word{i}')
        self.assertFalse(self.snapshot()['chapter_complete'])
        self.record('write', 'A sentence I wrote')
        for i in range(3):
            self.record('listen', f'A spoken line {i}')
        data = self.snapshot()
        self.assertTrue(data['chapter_complete'])
        self.assertEqual(data['quest_done'], 3)
        self.assertEqual(data['xp'], 50 + 15 + 12 + 20)
        self.record('listen', 'Another spoken line')
        self.assertEqual(self.snapshot()['xp'], data['xp'] + 4)
        self.assertEqual(self.snapshot()['counts']['chapter'], 1)
        self.store.undo_word('lemma:word0')
        undone = self.snapshot()
        self.assertFalse(undone['chapter_complete'])
        self.assertEqual(undone['xp'], data['xp'] + 4 - 10 - 20)
        self.record('learn', 'lemma:word0')
        self.assertEqual(self.snapshot()['xp'], data['xp'] + 4)

    def test_badges_persist_and_week_counts_only_practice_days(self):
        self.record('learn', 'lemma:pause')
        first = self.snapshot()
        self.assertTrue(next(b for b in first['badges'] if b['key'] == 'spark')['earned'])
        for day in [8, 10]:
            self.store.record('write', f'Day {day}', now=datetime(2026, 10, day, 12, tzinfo=timezone.utc))
        later = self.store.snapshot(now=datetime(2026, 10, 10, 12, tzinfo=timezone.utc))
        self.assertEqual(later['active_days'], 3)
        self.assertEqual(later['streak'], 1)
        self.assertTrue(next(b for b in later['badges'] if b['key'] == 'rhythm')['earned'])
        self.assertEqual(len(later['week']), 7)
        self.assertEqual(sum(w['xp'] for w in later['week']), 40)

    def test_mark_hook_rewards_only_new_knowledge_and_keeps_the_card(self):
        from types import SimpleNamespace as NS
        from vocab.known_store import KnownStore
        from vocab.entry import Unit
        from srs.store import CardStore
        from srs.scheduler import SM2Scheduler
        from web.handlers import Viewer
        static = {Unit.lemma('ich')}
        marked = KnownStore(self.config)
        class MiniViewer(Viewer):
            @property
            def known(self):
                return static | marked.units()
        viewer = MiniViewer.__new__(MiniViewer)
        viewer.app = NS(journey=self.store,marked_known=marked,card_store=CardStore(self.config),
                        scheduler=SM2Scheduler(),snoozes=NS(wake=lambda u:None,advance=lambda:None))
        viewer._stuck = {}; viewer._scopes = {}; viewer._known = None; viewer._queue_rescore = lambda u:None
        form = dict(kind='lemma',key='pause',action='known')
        viewer.mark_known(form);viewer.mark_known(form)
        self.assertEqual(self.store.snapshot()['xp'], 10)
        self.assertIsNotNone(viewer.app.card_store.get(Unit.lemma('pause')))
        viewer.mark_known(dict(form,key='ich'))
        self.assertEqual(self.store.snapshot()['xp'], 10)
        viewer.mark_known(dict(form,action='undo'))
        self.assertEqual(self.store.snapshot()['xp'], 0)
        self.assertIsNone(viewer.app.card_store.get(Unit.lemma('pause')))
        viewer.mark_known(form)
        self.assertEqual(self.store.snapshot()['xp'], 10)

    def test_review_hook_rewards_due_recalls_and_graduation_once(self):
        from dataclasses import replace
        from types import SimpleNamespace as NS
        from datetime import timedelta
        from vocab.entry import Unit
        from srs.store import CardStore
        from srs.scheduler import SM2Scheduler
        from web.handlers import Viewer
        viewer = Viewer.__new__(Viewer)
        scheduler = SM2Scheduler();cards = CardStore(self.config)
        viewer.app = NS(journey=self.store,scheduler=scheduler,card_store=cards)
        unit = Unit.lemma('pause')
        future = scheduler.claimed(unit,datetime.now());cards.add(future)
        viewer._grade_card(future,True)
        self.assertEqual(self.store.snapshot()['xp'], 0)
        self.assertEqual(cards.get(unit).repetitions, 0)
        self.assertEqual(cards.get(unit).due_date, future.due_date)
        due = replace(future,due_date=datetime.now()-timedelta(days=1),repetitions=4)
        cards.save(due)
        viewer._grade_card(due,True)
        self.assertEqual(self.store.snapshot()['xp'], 12+25)
        self.assertIsNone(cards.get(unit))
        viewer._grade_card(due,True)
        self.assertEqual(self.store.snapshot()['xp'], 12+25)

    def test_own_sentence_recall_rewards_only_the_due_attempt(self):
        from types import SimpleNamespace
        from vocab.own_sentences import OwnSentences
        from web.handlers import Viewer
        own = OwnSentences(self.config)
        own.add("Ich brauche eine Pause.", "I need a break.")
        viewer = SimpleNamespace(app=SimpleNamespace(own=own,journey=self.store))
        Viewer._grade_own(viewer, "Ich brauche eine Pause.", True)
        data = self.store.snapshot()
        self.assertEqual(data['xp'], 12)
        Viewer._grade_own(viewer, "Ich brauche eine Pause.", True)
        Viewer._grade_own(viewer, "Nonexistent sentence", True)
        self.assertEqual(self.store.snapshot()['xp'], 12)

    def test_heard_rewards_require_completed_playback_and_do_not_duplicate_encounters(self):
        from types import SimpleNamespace
        from vocab.encounters import Encounters
        from vocab.entry import Unit
        from web.handlers import Viewer
        encounters = Encounters(self.config)
        viewer = SimpleNamespace(app=SimpleNamespace(encounters=encounters,journey=self.store))
        line = dict(text="Ich brauche eine Pause.",video="abcdefghijk",at=0,
                    words=[["Pause", "lemma", "pause"]])
        self.assertEqual(Viewer.heard(viewer,[line])['journey']['xp'], 0)
        line['reward'] = True
        self.assertEqual(Viewer.heard(viewer,[line])['journey']['xp'], 4)
        self.assertEqual(Viewer.heard(viewer,[line])['journey']['xp'], 4)
        self.assertEqual(encounters.count(Unit.lemma('pause')), 1)

    def test_calendar_uses_configured_day_at_midnight(self):
        midnight = datetime(2026, 10, 7, 22, tzinfo=timezone.utc)
        self.store.record('write', 'At midnight', now=midnight)
        data = self.store.snapshot(now=midnight)
        self.assertEqual(data['day'], '2026-10-08')
        self.assertEqual(data['today_xp'], 15)

    def test_spaced_recall_retries_and_invalid_activity_do_not_duplicate(self):
        self.assertEqual(self.record('recall', 'lemma:pause:due-2026-10-07'), 12)
        self.assertEqual(self.record('recall', 'lemma:pause:due-2026-10-07'), 0)
        self.assertEqual(self.record('scroll', 'reel'), 0)
        self.assertEqual(self.record('write', ''), 0)
        self.assertEqual(self.snapshot()['xp'], 12)


def test_levels_show_true_distance_to_the_next_chapter():
    for points, level in [(0,1),(49,1),(50,2),(129,2),(130,3),(380,5)]:
        data = level_for(points)
        assert data['level'] == level
        assert data['floor'] <= points < data['ceiling']
        assert data['remaining'] == data['ceiling'] - points
        assert 0 <= data['percent'] <= 100


def test_reels_has_one_persistent_player_and_no_application_menus():
    import json
    from web.reels import feed
    from web.render import layout
    from web.watch import stage
    row = {'video':'abc12345678','comprehension':.8}
    body = feed(title='A real voice', row=row,
                state=json.dumps({'at':0,'total':2,'src':'subtitle','list':'travel','video':row['video']}),
                exit_url='/?src=subtitle&list=travel', atlas_url='/journey',
                scoreboard='',panel='',taste='',ordering='',player=stage(row['video'],0),
                pager='',script='')
    html = layout('Reels',body,'/reels','subtitle','travel')
    assert "class='reels-page'" in html
    assert 'Main navigation' not in html
    assert 'Quick navigation' not in html
    assert "class='workspace-top'" not in html
    assert html.count("id='player'") == 1
    assert "id='reel-track'" in html
    assert "id='reel-drawer'" in html
    assert "id='caption'" in html
    assert "class='caption'" in html
    assert 'list=travel' in html
    assert html.count('app.js?v=') == 1
