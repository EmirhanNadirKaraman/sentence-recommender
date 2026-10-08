"""Annotate private video-picker cards using the project's German POS model."""
import json
from pathlib import Path
import re

NOUN = re.compile(r'^(?:der|die|das)\s+([A-ZÄÖÜ][\wÄÖÜäöüßé-]*)')


def annotate(cards, nlp):
    from vocab.aliases import heads
    names = [heads(c['word'], 'de') for c in cards]
    words = sorted({word for group in names for word in group})
    tags = {word: [token.pos_ for token in doc] for word, doc in zip(words, nlp.pipe(words))}
    contextual = {word: [token.pos_ for token in doc if token.text == word] for word, doc in zip(words, nlp.pipe('Wir wollen '+word+'.' for word in words))}
    def verb(word, frame):
        if any(pos in {'VERB', 'AUX'} for pos in tags[word] + contextual[word]):
            return True
        return bool(re.search(r'(?:en|ern|eln)$', word)) and (bool(re.search(r'\b(?:sich|etw|jdn|jdm|jds)\b', frame)) or ',' in frame or word.startswith(('herein', 'heraus', 'hinein', 'hinaus')))
    for card, group in zip(cards, names):
        noun = NOUN.match(card['word'])
        if noun:
            category = 'noun'
        elif group and all(verb(word, card['word']) for word in group):
            category = 'verb'
        elif group and all(any(pos in {'NOUN', 'PROPN'} for pos in tags[word]) for word in group):
            category = 'noun'
        else:
            category = 'other'
        card['category'] = category
        card.pop('auto_yes', None)
        head = noun.group(1) if noun else next(iter(group)) if len(group) == 1 else ''
        if category == 'noun' and head.lower().endswith('ung'):
            card['auto_yes'] = {'text': f'İsim -ung ile bitiyor: {head}. Senin kuralına göre otomatik Evet.'}
    return cards


def main():
    import sys
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import spacy
    from tools.screen_video_word_picker import write
    path = root / 'docs/video-selection/emir-video-words-snapshot.json'
    snapshot = json.loads(path.read_text())
    annotate(snapshot['cards'], spacy.load('de_core_news_md', disable=['parser', 'ner']))
    write(snapshot, path)
    from collections import Counter
    print(dict(Counter(c['category'] for c in snapshot['cards'])))
    print('Auto yes:', sum('auto_yes' in c for c in snapshot['cards']))


if __name__ == '__main__':
    main()
