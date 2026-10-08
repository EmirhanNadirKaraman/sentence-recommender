"""Build a private, offline yes/no picker from a reader's unknown study goals.

Run: .venv/bin/python tools/build_video_word_picker.py
No progress changes, no model calls and no video generation.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import Settings
from context import Application
from readers import Registry
from vocab.search import word_families


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reader', default='emir')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/video-selection')
    args = parser.parse_args()
    reader = Registry().get(args.reader)
    if reader is None or reader.language != 'de':
        raise SystemExit('Choose an existing German-learning reader.')
    app = Application(Settings.for_reader(reader))
    known = app.known_set().units
    goals = tuple(dict.fromkeys(app.goal_units))
    unknown = [unit for unit in goals if unit not in known]
    rank = {u: i + 1 for i, u in enumerate(goals)}
    cards = []
    for parent, members in word_families(goals, 'de').items():
        missing = [u for u in members if u not in known]
        if not missing:
            continue
        cards.append({'id': f'{parent.kind}:{parent.key}', 'word': missing[0].key if parent in known and len(missing) == 1 else parent.key,
                      'head_known': parent in known, 'rank': min(rank[u] for u in missing),
                      'members': [{'kind': u.kind, 'key': u.key} for u in missing]})
    cards.sort(key=lambda c: c['rank'])
    import spacy
    from tools.group_video_words import annotate
    annotate(cards, spacy.load('de_core_news_md', disable=['parser', 'ner']))
    snapshot = {'schema': 1, 'reader': reader.name, 'language': 'de',
                'source': str(app.settings.goal_words.relative_to(ROOT)),
                'created': datetime.now(ZoneInfo('Europe/Istanbul')).isoformat(timespec='seconds'),
                'total_goals': len(goals), 'unknown_count': len(unknown), 'cards': cards}
    args.output.mkdir(parents=True, exist_ok=True)
    stem = f'{reader.name}-video-words'
    (args.output / f'{stem}-unknown.txt').write_text('\n'.join(u.key for u in unknown) + '\n', encoding='utf-8')
    (args.output / f'{stem}-snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    template = (ROOT / 'tools/video_word_picker.html').read_text(encoding='utf-8')
    # JSON is data, never an interpolated executable script or HTML fragment.
    payload = json.dumps(snapshot, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    (args.output / f'{stem}.html').write_text(template.replace('__SNAPSHOT__', payload), encoding='utf-8')
    print(json.dumps({'unknown_units': len(unknown), 'selection_cards': len(cards),
                     'html': str(args.output / f'{stem}.html')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
