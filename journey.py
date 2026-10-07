"""Reader-owned progression. Rewards follow accepted learning actions, never page views."""
from __future__ import annotations
from datetime import datetime, timedelta
from hashlib import sha256
import os
from zoneinfo import ZoneInfo

from state import ensure, open_state

SCHEMA = """
CREATE TABLE IF NOT EXISTS journey_event (
    identity TEXT COLLATE "C" PRIMARY KEY,
    kind TEXT NOT NULL,
    day DATE NOT NULL,
    points INTEGER NOT NULL CHECK (points >= 0),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS journey_event_day ON journey_event(day);
CREATE TABLE IF NOT EXISTS journey_badge (
    key TEXT COLLATE "C" PRIMARY KEY,
    earned DATE NOT NULL
);
"""
POINTS = {'learn': 10, 'recall': 12, 'practice': 3, 'listen': 4, 'write': 15, 'master': 25}
BADGES = (
    ('spark', 'First light', 'Learn your first new word', 'learn', 1),
    ('trail', 'Trail maker', 'Learn 10 new words', 'learn', 10),
    ('lexicon', 'Word architect', 'Learn 50 new words', 'learn', 50),
    ('library', 'A world of words', 'Learn 100 new words', 'learn', 100),
    ('echo', 'Memory spark', 'Recall your first word', 'recall', 1),
    ('keeper', 'Memory keeper', 'Recall 25 words in spaced practice', 'recall', 25),
    ('voice', 'Real voices', 'Listen through 3 distinct subtitle lines', 'listen', 3),
    ('listener', 'Tuned in', 'Listen through 30 distinct subtitle lines', 'listen', 30),
    ('author', 'Your own voice', 'Keep your first original sentence', 'write', 1),
    ('master', 'Made it stick', 'Graduate a word through spaced recall', 'master', 1),
    ('rhythm', 'Finding your rhythm', 'Practise on 3 different days', 'days', 3),
    ('orbit', 'In your orbit', 'Practise on 7 different days', 'days', 7),
    ('chapter', 'A complete chapter', 'Finish a daily expedition', 'chapter', 1),
)
RANKS = ('First light', 'Trail maker', 'Pathfinder', 'Explorer', 'Story seeker',
         'Wayfinder', 'World builder')


def threshold(level: int) -> int:
    n = max(0, level - 1)
    return 50 * n + 15 * n * (n - 1)


def level_for(points: int) -> dict:
    level = 1
    while points >= threshold(level + 1):
        level += 1
    start, end = threshold(level), threshold(level + 1)
    return {'level': level, 'rank': RANKS[min(level - 1, len(RANKS) - 1)],
            'floor': start, 'ceiling': end, 'remaining': end - points,
            'percent': round(100 * (points - start) / (end - start))}


def calendar(now=None):
    zone = ZoneInfo(os.environ.get('APP_TIMEZONE', 'Europe/Istanbul'))
    moment = now or datetime.now(zone)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(zone).date()


class JourneyStore:
    def __init__(self, config):
        self._db = config
        ensure(config, SCHEMA)
        # A browser can serve several accounts; snapshots must not cross them.
        self.identity = sha256(f'{config.name}/{config.schema}'.encode()).hexdigest()[:16]

    def record(self, kind: str, entity: str, *, now=None):
        if kind not in POINTS or not entity:
            return 0
        day = calendar(now)
        token = sha256(entity.encode()).hexdigest()
        identity = f'{kind}:{token}' if kind in ('learn', 'write', 'master') else f'{kind}:{day}:{token}'
        with open_state(self._db) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                         ('journey:' + self._db.schema,))
            # Listening has a bounded daily reward. Replaying one line never
            # produces more points that day; changing videos alone produces none.
            if kind == 'listen':
                count = conn.execute("SELECT count(*) FROM journey_event WHERE day=%s "
                                     "AND kind='listen' AND active", (day,)).fetchone()[0]
                if count >= 20:
                    return 0
            conflict = ("ON CONFLICT (identity) DO UPDATE SET active=TRUE,points=excluded.points "
                        "WHERE NOT journey_event.active" if kind == 'learn' else "ON CONFLICT DO NOTHING")
            row = conn.execute(
                "INSERT INTO journey_event(identity,kind,day,points) VALUES (%s,%s,%s,%s) "
                + conflict + " RETURNING points,day",
                (identity, kind, day, POINTS[kind])).fetchone()
            if row:
                self._complete(conn, row[1])
            return row[0] if row else 0

    def undo_word(self, entity: str):
        identity = 'learn:' + sha256(entity.encode()).hexdigest()
        with open_state(self._db) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                         ('journey:' + self._db.schema,))
            row = conn.execute("UPDATE journey_event SET points=0, active=FALSE WHERE identity=%s RETURNING day",
                               (identity,)).fetchone()
            if row:
                self._complete(conn, row[0])
        # Identity and its original day are kept: relearning restores the same
        # reward; it cannot accumulate a second reward or a new daily quest.

    @staticmethod
    def _totals(conn, day):
        return dict(conn.execute(
            "SELECT kind,count(*) FROM journey_event WHERE active AND day=%s GROUP BY kind",
            (day,)).fetchall())

    def _complete(self, conn, day):
        counts = self._totals(conn, day)
        if (counts.get('learn', 0) >= 5 and counts.get('listen', 0) >= 3
                and sum(counts.get(k, 0) for k in ('recall', 'practice', 'write')) >= 1):
            conn.execute("INSERT INTO journey_event(identity,kind,day,points) "
                         "VALUES (%s,'chapter',%s,20) ON CONFLICT (identity) DO UPDATE SET points=20,active=TRUE",
                         ('chapter:' + str(day), day))
        else:
            conn.execute("UPDATE journey_event SET points=0,active=FALSE WHERE identity=%s",
                         ('chapter:' + str(day),))

    def snapshot(self, *, now=None):
        day = calendar(now)
        with open_state(self._db) as conn:
            rows = conn.execute("SELECT kind,count(*),COALESCE(sum(points),0) "
                                "FROM journey_event WHERE active GROUP BY kind").fetchall()
            counts = {kind: count for kind, count, _ in rows}
            points = sum(total for _, _, total in rows)
            today = self._totals(conn, day)
            days = [row[0] for row in conn.execute(
                "SELECT DISTINCT day FROM journey_event WHERE active AND points>0 ORDER BY day"
            ).fetchall()]
            counts['days'] = len(days)
            earned = {key: str(when) for key, when in
                      conn.execute("SELECT key,earned FROM journey_badge").fetchall()}
            for key, _, _, kind, target in BADGES:
                if key not in earned and counts.get(kind, 0) >= target:
                    row = conn.execute("INSERT INTO journey_badge(key,earned) VALUES (%s,%s) "
                                       "ON CONFLICT DO NOTHING RETURNING earned", (key, day)).fetchone()
                    if row is None:
                        row = conn.execute("SELECT earned FROM journey_badge WHERE key=%s", (key,)).fetchone()
                    earned[key] = str(row[0])
            week_start = day - timedelta(days=6)
            week = {str(when): total for when, total in conn.execute(
                "SELECT day,sum(points) FROM journey_event WHERE active AND day >= %s "
                "GROUP BY day", (week_start,)).fetchall()}
        quests = [
            {'key': 'discover', 'name': 'Open five new doors', 'detail': 'Learn 5 new words',
             'value': min(today.get('learn', 0), 5), 'target': 5, 'path': '/', 'icon': 'spark'},
            {'key': 'remember', 'name': 'Make it yours', 'detail': 'One review or original sentence',
             'value': min(sum(today.get(k, 0) for k in ('recall', 'practice', 'write')), 1),
             'target': 1, 'path': '/review' if counts.get('learn', 0) else '/mine', 'icon': 'echo'},
            {'key': 'listen', 'name': 'Follow a real voice', 'detail': 'Listen through 3 subtitle lines',
             'value': min(today.get('listen', 0), 3), 'target': 3, 'path': '/reels', 'icon': 'voice'},
        ]
        # Always offer writing as an alternative; new words' reviews are due tomorrow.
        quests[1]['alternative'] = '/mine'
        current = 0
        cursor = day if day in days else day - timedelta(days=1)
        seen = set(days)
        while cursor in seen:
            current += 1
            cursor -= timedelta(days=1)
        badges = [dict(key=key, name=name, detail=detail, value=min(counts.get(kind, 0), target),
                       target=target, earned=earned.get(key))
                  for key, name, detail, kind, target in BADGES]
        return {'identity': self.identity, 'day': str(day), 'xp': points, **level_for(points),
                'today_xp': sum(POINTS.get(k, 20 if k == 'chapter' else 0) * v
                                for k, v in today.items()),
                'counts': counts, 'quests': quests, 'quest_done': sum(q['value'] >= q['target'] for q in quests),
                'chapter_complete': bool(today.get('chapter')), 'active_days': len(days),
                'streak': current, 'badges': badges,
                'week': [{'day': str(week_start + timedelta(days=n)),
                          'xp': int(week.get(str(week_start + timedelta(days=n)), 0))}
                         for n in range(7)]}
