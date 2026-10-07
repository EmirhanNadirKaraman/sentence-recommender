"""The language atlas: pure rendering of reader-owned, measured progress."""
from html import escape
import json


GLYPHS = {
    'spark': 'M16 3l3.2 8.8L28 15l-8.8 3.2L16 27l-3.2-8.8L4 15l8.8-3.2z',
    'trail': 'M4 25c10 0 3-12 13-12h8 M20 8l5 5-5 5 M7 4l2 4 4 2-4 2-2 4-2-4-4-2 4-2z',
    'lexicon': 'M5 25V10h6v15 M13 25V5h6v20 M21 25V14h6v11 M3 28h26',
    'library': 'M16 9c-4-4-9-4-13-2v19c5-2 9-1 13 2c4-3 8-4 13-2V7c-4-2-9-2-13 2z M16 9v19 M7 12h5 M7 17h5 M21 12h4 M21 17h4',
    'keeper': 'M16 3L5 8v8c0 6 6 11 11 13c5-2 11-7 11-13V8z M10 16l4 4 8-9',
    'rhythm': 'M5 7h22v21H5z M10 3v8 M22 3v8 M5 13h22 M10 21l4 3 8-7',
    'listener': 'M5 17v-2a11 11 0 0 1 22 0v2 M5 15h5v11H5z M22 15h5v11h-5z M27 26c0 3-4 4-8 4',
    'chapter': 'M5 28V4 M5 5h21l-5 7 5 7H5 M10 25l4-4 4 4 5-5',
    'echo': 'M8 8a11 11 0 1 1-1 15 M4 4v8h8 M16 9v7l5 3',
    'voice': 'M5 14v5 M10 8v17 M16 3v26 M22 8v17 M27 14v5',
    'author': 'M7 22L23 6l4 4-16 16-6 1z M19 10l4 4',
    'master': 'M7 4h18v9a9 9 0 0 1-18 0z M7 7H3v4a6 6 0 0 0 6 6 M25 7h4v4a6 6 0 0 1-6 6 M16 22v6 M10 28h12',
    'orbit': 'M16 4a12 12 0 1 0 0 24a12 12 0 1 0 0-24 M4 16h24 M16 4c8 7 8 17 0 24c-8-7-8-17 0-24',
}


def glyph(key):
    return ("<svg viewBox='0 0 32 32' fill='none' stroke='currentColor' stroke-width='1.6' "
            "stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>"
            f"<path d='{GLYPHS.get(key, GLYPHS['spark'])}'/></svg>")


def atlas(data, large=False):
    level = data['level']
    stars = [(65, 132), (127, 101), (197, 129), (246, 67), (320, 100), (365, 42), (431, 79)]
    count = (level - 1) % len(stars) + 1
    region = (level - 1) // len(stars) + 1
    land = [
        'M0 206l50-29 50 15 72-43 62 34 48-47 61 34 54-27 103 37v60H0z',
        'M0 212l55-60 40 20 65-95 70 116 67-103 59 91 65-45 79 79v25H0z',
        'M0 210q60-20 110 0t110 0t110 0t170 0v30H0z M100 207q30-45 62 0 M306 207q26-60 58 0'
    ][(region - 1) % 3]
    sky = ['#122348','#172247','#0f273a'][(region - 1) % 3]
    points = ' '.join(f'{x},{y}' for x, y in stars)
    nodes = ''.join(
        f"<g data-atlas-step='{i+1}' class='atlas-star {'lit' if i < count else 'sleeping'}' style='--delay:{i * .2}s'>"
        f"<circle cx='{x}' cy='{y}' r='{12 if i == count - 1 else 7}'/>"
        f"<path d='M{x-4} {y}h8 M{x} {y-4}v8'/></g>" for i, (x, y) in enumerate(stars))
    return (
        f"<div class='atlas-scene {'atlas-large' if large else ''}' role='img' "
        f"aria-label='Your atlas grows with your journey: level {level}'>"
        "<svg viewBox='0 0 500 240' fill='none' aria-hidden='true'>"
        "<defs><linearGradient id='atlas-sky' x2='1' y2='1'>"
        f"<stop data-atlas-sky stop-color='{sky}'/><stop offset='1' stop-color='#071122'/></linearGradient>"
        "<linearGradient id='atlas-land' x2='0' y2='1'><stop stop-color='#236dd2'/>"
        "<stop offset='1' stop-color='#143360'/></linearGradient></defs>"
        "<rect width='500' height='240' rx='28' fill='url(#atlas-sky)'/>"
        "<circle cx='410' cy='46' r='18' fill='#dceaff' opacity='.08'/>"
        "<g fill='#82b9ff' opacity='.6'><circle cx='31' cy='35' r='1.5'/>"
        "<circle cx='163' cy='27' r='1'/><circle cx='292' cy='31' r='1.5'/>"
        "<circle cx='462' cy='129' r='1'/><circle cx='224' cy='22' r='1'/></g>"
        f"<path data-atlas-land d='{land}' fill='url(#atlas-land)'/>"
        "<path d='M0 228l84-31 79 32 62-17 69 18 80-27 126 28' stroke='#3686e9' opacity='.4'/>"
        f"<polyline points='{points}' stroke='#a9cfff' stroke-opacity='.2' stroke-width='1.5' stroke-dasharray='4 6'/>"
        f"<polyline points='{' '.join(f'{x},{y}' for x,y in stars[:count])}' "
        "stroke='#80b9ff' stroke-width='2' class='atlas-thread'/>" + nodes
        + "<path d='M65 155v22 M61 159l4-4 4 4' stroke='#d4e6ff'/>"
        "<text x='28' y='218' fill='#b5d2fb' font-size='9' letter-spacing='2'>A LITTLE MORE OF THE WORLD, YOURS.</text>"
        f"</svg><span class='atlas-coordinate'>✦ YOUR LANGUAGE ATLAS · <span data-atlas-region>REGION {region}</span></span></div>"
    )


def hud(data, suffix=''):
    return (
        f"<a class='journey-hud' href='/journey{suffix}' aria-label='Your journey, level {data['level']}, {data['xp']} XP'>"
        f"<span class='level-orb' style='--fill:{data['percent']}%' data-journey='level'>{data['level']}</span>"
        "<span><small>YOUR JOURNEY</small>"
        f"<strong><span data-journey='xp'>{data['xp']:,}</span> XP</strong></span>"
        f"<span class='hud-quests' data-journey='quests'>{data['quest_done']}/3</span></a>"
    )


def quests(data, suffix=''):
    cards = []
    for q in data['quests']:
        complete = q['value'] >= q['target']
        alternate = (f"<a class='quest-alternative' href='/mine{suffix}'>Or write a sentence ↗</a>"
                     if q['key'] == 'remember' else '')
        cards.append(
            f"<article class='quest-card {'complete' if complete else ''}' data-quest='{q['key']}'>"
            f"<span class='quest-symbol'>{glyph(q['icon'])}</span>"
            f"<span class='quest-count' data-quest-count>{q['value']}/{q['target']}</span>"
            f"<h3>{escape(q['name'])}</h3><p>{escape(q['detail'])}</p>"
            f"<progress value='{q['value']}' max='{q['target']}' aria-label='{escape(q['detail'])}'></progress>"
            f"<a class='quest-go' href='{q['path']}{suffix}'>{'Explore more' if complete else 'Let’s go'} ↗</a>"
            + alternate + "</article>")
    done = data['chapter_complete']
    return (
        "<section class='daily-expedition' aria-labelledby='expedition-title'>"
        "<div class='expedition-heading'><div><span class='eyebrow'>TODAY’S EXPEDITION</span>"
        f"<h2 id='expedition-title'>{'A chapter well spent.' if done else 'Small quests. Real growth.'}</h2></div>"
        f"<span class='chapter-reward'>{'✓ Chapter complete' if done else '✦ Complete all three · +20 XP'}</span></div>"
        "<div class='quest-grid'>" + ''.join(cards) + "</div></section>")


def home(data, suffix=''):
    return (
        "<section class='journey-hero'><div class='journey-hero-copy'>"
        "<span class='eyebrow'>LITTLE BY LITTLE, A WHOLE NEW WORLD.</span>"
        "<h1>Your world is<br>getting bigger.</h1>"
        "<p>Every word opens a door. Every recall makes it yours.</p>"
        f"<div class='journey-rank'><span class='rank-star'>✦</span><strong data-journey='rank'>{escape(data['rank'])}</strong>"
        f"<span>Journey level <b data-journey='level'>{data['level']}</b></span></div>"
        f"<div class='xp-line'><span><b data-journey='xp'>{data['xp']:,}</b> XP</span>"
        f"<span data-journey='remaining'>{data['remaining']} to level {data['level'] + 1}</span></div>"
        f"<progress class='xp-progress' value='{data['xp'] - data['floor']}' max='{data['ceiling'] - data['floor']}' "
        "aria-label='Journey level progress'></progress>"
        "<a class='go' href='#reading-top'>Find your next discovery</a>"
        f"<a class='hero-secondary' href='/journey{suffix}'>Visit your atlas</a>"
        "</div>" + atlas(data) + "</section>" + quests(data, suffix))


def page(data, suffix=''):
    owned = [b for b in data['badges'] if b['earned']]
    badges = ''.join(
        f"<article class='achievement {'earned' if b['earned'] else 'locked'}'>"
        f"<div class='achievement-medallion'>{glyph(b['key'])}</div>"
        f"<span class='achievement-status'>{'UNLOCKED' if b['earned'] else 'NEXT DISCOVERY'}</span>"
        f"<h3>{escape(b['name'])}</h3><p>{escape(b['detail'])}</p>"
        + (f"<span class='earned-date'>Earned {b['earned']}</span>" if b['earned'] else
           f"<progress value='{b['value']}' max='{b['target']}' aria-label='{escape(b['detail'])}'></progress>"
           f"<small>{b['value']} / {b['target']}</small>") + "</article>"
        for b in data['badges'])
    week = ''.join(
        f"<div class='week-day {'active' if w['xp'] else ''}'><span>{glyph('spark')}</span>"
        f"<strong>{w['xp']} XP</strong><small>{w['day'][5:]}</small></div>"
        for w in data['week'])
    return (
        "<div class='journey-heading'><span class='eyebrow'>YOUR LANGUAGE ATLAS</span>"
        "<h1>Look how far<br>you’ve come.</h1><p>A collection of small wins. A world that keeps growing.</p></div>"
        "<section class='atlas-panel'>" + atlas(data, True)
        + "<div class='atlas-summary'>"
        f"<span class='eyebrow'>CHAPTER {data['level']}</span><h2 data-journey='rank'>{escape(data['rank'])}</h2>"
        f"<p data-journey='remaining'>{data['remaining']} to level {data['level'] + 1}</p>"
        f"<progress value='{data['xp'] - data['floor']}' max='{data['ceiling'] - data['floor']}' aria-label='Journey level progress'></progress>"
        "<span class='journey-footnote'>Every seven chapters opens a new region. Journey levels celebrate practice; they aren’t language proficiency scores.</span>"
        "</div></section>"
        "<section class='journey-stats'>"
        f"<div><strong>{data['xp']:,}</strong><span>Total XP</span></div>"
        f"<div><strong>{data['counts'].get('learn', 0)}</strong><span>New words explored</span></div>"
        f"<div><strong>{data['counts'].get('recall', 0)}</strong><span>Successful recalls</span></div>"
        f"<div><strong>{len(owned)}</strong><span>Achievements unlocked</span></div></section>"
        + quests(data, suffix)
        + "<section class='rhythm-panel'><div><span class='eyebrow'>YOUR PRACTICE RHYTHM</span>"
        f"<h2>{data['streak']} day{'s' if data['streak'] != 1 else ''} in your rhythm.</h2>"
        "<p>Come back when you can. Your atlas and achievements stay yours.</p></div>"
        "<div class='week-strip'>" + week + "</div></section>"
        f"<section class='achievement-collection'><div class='expedition-heading'><div>"
        f"<span class='eyebrow'>THE LITTLE THINGS THAT ADD UP</span><h2>Your achievement collection.</h2></div>"
        f"<span class='quiet'>{len(owned)} / {len(data['badges'])} unlocked</span></div>"
        "<div class='achievement-grid'>" + badges + "</div></section>"
        "<details class='reward-rules'><summary>How your journey grows</summary>"
        "<p>New word +10 XP · successful spaced recall +12 · honest practice +3 · "
        "distinct subtitle line +4 (up to 20 a day) · original sentence +15 · graduated word +25. "
        "Finish the three daily quests for +20 XP. Refreshing, replaying the same line, "
        "or marking a word repeatedly earns no extra XP. Undo takes back that word’s XP; relearning restores that same reward, never a second one. Your atlas tracks practice from this update; your existing vocabulary stays in your learning progress.</p>"
        "</details><label class='reward-sound'><input type='checkbox' id='reward-sound'> "
        "Play a soft sound for milestones</label>"
    )


def state(data):
    return ("<script type='application/json' id='journey-state'>"
            + json.dumps(data, ensure_ascii=False).replace('<', '\\u003c') + "</script>")
