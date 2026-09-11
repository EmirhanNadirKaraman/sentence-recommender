"""Which assembled sentences are worth teaching.

Applied after correction, before unit analysis.  Every rejection is counted so
`build` can report what the corpus actually cost — a silent filter that halves
the pool is worse than no filter.
"""
from __future__ import annotations

import re
from collections import Counter

from corpus.sentence import TRANSCRIPT, Sentence
from vocab.loader import normalize

# `–` and `—` are the dash subtitles use to mark a change of speaker, so a
# line carrying one is two people talking, not one sentence.
# Never a word, wherever it came from: bracketed stage directions, music
# marks, markup that survived the scrape.
LEFTOVER_ARTIFACT = re.compile(r"[\[\]<>_♪*]")

# Junk in a caption and ordinary punctuation in prose. A subtitle uses a dash
# to mark a change of speaker and an ellipsis to mark the line continuing into
# the next cue, so either one means the sentence in hand is a piece of
# something rather than the thing itself. A written transcript uses both the
# way any writer does.
#
# Applied to subtitles only, and the difference is not small: of 148,553
# sentences read out of the Easy German transcripts, 50,989 were refused as
# artifacts and 50,794 of those carried nothing worse than a dash.
CAPTION_ARTIFACT = re.compile(r"[…–—]|--|\.\.\.| - ")

# Pictographs and emoji. Captions are full of them and they are not words.
PICTOGRAPH = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2190-\u21FF]")

# A capitalised word said three times over is a caption artefact — a chant, a
# name repeated by two speakers — not a sentence: "Frau Brust Frau Frau Güll."
# German capitalises every noun, so capitalisation alone says nothing; the
# repetition is what gives it away.
NAME_CHANT = 3
ALPHANUMERIC = re.compile(r"\W+", re.UNICODE)

# Letters German is written with. Anything else — Thai, Cyrillic, Greek, CJK,
# Arabic — is another language's script, not a German sentence.
LATIN = re.compile(r"[A-Za-zÄÖÜäöüß]")
LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
FOREIGN_SCRIPT = 0.2

# Words that are English and are not also German. Deliberately excludes the
# lookalikes — `war`, `hat`, `will`, `man`, `all`, `in`, `so`, `die` — which
# would otherwise convict ordinary German sentences.
ENGLISH = frozenset("""
the and is are you your this that with have has not but they would could
about from just there what for my his her she he of on to it at be by or if
were been their don't it's i'm we're going know like think really because
""".split())

# Enough German to say the sentence is German even with English in it.
GERMAN = frozenset("""
der die das und ist sind ich nicht ein eine einen zu mit auf für dass aber
sich es den dem wir sie du war haben hat wird werden kann auch noch schon
wenn weil oder als wie so nur mal ja nein sehr mehr immer dann doch hier
jetzt was mir mich dir dich ihm ihr uns euch von im am zum zur
""".split())


class SentenceFilter:
    """Rejects fragments, artifacts, and repeats.

    `min_tokens`/`max_tokens` bound difficulty at both ends: below the floor a
    sentence carries too little context to learn from, above the ceiling a
    single unknown word is not really what makes it hard.
    """

    def __init__(self, min_tokens: int = 4, max_tokens: int = 25) -> None:
        self._min = min_tokens
        self._max = max_tokens
        self.rejected: Counter[str] = Counter()
        self._seen: set[str] = set()

    def keep(self, sentence: Sentence) -> bool:
        reason = self._reject_reason(sentence)
        if reason:
            self.rejected[reason] += 1
            return False
        self._seen.add(self._fingerprint(sentence.text))
        return True

    def apply(self, sentences: list[Sentence]) -> list[Sentence]:
        return [s for s in sentences if self.keep(s)]

    def split(self, sentences: list[Sentence]) -> tuple[list[Sentence], list[Sentence]]:
        """Both halves: what to teach from, and what was set aside.

        The rejects are not waste for a subtitle build. This filter decides
        what is worth *learning* from — a sentence can be too long, or too
        short, or a near-duplicate, and still be part of what was said. An
        overlay built only from the survivors has holes in it.
        """
        kept, dropped = [], []
        for sentence in sentences:
            (kept if self.keep(sentence) else dropped).append(sentence)
        return kept, dropped

    def _reject_reason(self, sentence: Sentence) -> str | None:
        text = sentence.text.strip()
        if not text:
            return "empty"
        if LEFTOVER_ARTIFACT.search(text):
            return "artifact"
        if sentence.origin != TRANSCRIPT and CAPTION_ARTIFACT.search(text):
            return "artifact"
        if not text.endswith((".", "!", "?")):
            return "unterminated"
        words = text.split()
        if not (self._min <= len(words) <= self._max):
            return "length"
        if self._fingerprint(text) in self._seen:
            return "duplicate"
        if self._not_german(text, words):
            return "not german"
        if PICTOGRAPH.search(text):
            return "pictograph"
        if self._repeats(words):
            return "repeats itself"
        return None

    @staticmethod
    def _repeats(words: list[str]) -> bool:
        """Whether the line is one thing said twice.

        Subtitles repeat: the same caption arrives from two cues, or a
        speaker echoes themselves — "Ich warte. Ich warte." Half the words
        are then teaching nothing, and the sentence is chosen *because* it is
        short. Two tests: the line is two identical halves, or one word
        carries it by being said three times over.
        """
        plain = [ALPHANUMERIC.sub("", w.lower()) for w in words]
        plain = [w for w in plain if w]
        if not plain:
            return True
        half = len(plain) // 2
        if half and plain[:half] == plain[half:half * 2]:
            return True
        return max(Counter(plain).values()) >= NAME_CHANT

    @staticmethod
    def _not_german(text: str, words: list[str]) -> bool:
        """Whether this is a German sentence at all.

        Subtitles carry whatever was on screen, and some of it is not German:
        an English song lyric, a line of Thai. Analysed as German they yield
        junk units, and one of them was chosen as the sentence teaching step
        nine of the roadmap — "If I stand to be on my own…", offered as an
        example of `jdm. (Dat) stehen`.

        Two tests, both deliberately blunt. A fifth of the letters outside
        the Latin alphabet means another script. Otherwise the sentence is
        weighed: English marker words against German ones, and English has to
        both appear at least twice and outnumber the German, so a German
        sentence with a loanword or a brand name in it survives.
        """
        letters = LETTER.findall(text)
        if letters:
            foreign = sum(1 for c in letters if not LATIN.match(c))
            if foreign / len(letters) > FOREIGN_SCRIPT:
                return True
        plain = [ALPHANUMERIC.sub("", w.lower()) for w in words]
        english = sum(1 for w in plain if w in ENGLISH)
        german = sum(1 for w in plain if w in GERMAN)
        return english >= 2 and english > german

    @staticmethod
    def _fingerprint(text: str) -> str:
        return ALPHANUMERIC.sub("", normalize(text))
