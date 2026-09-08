"""Putting corrected sentences back on the video's clock.

The model rewrites the text, so a corrected sentence cannot simply inherit the
timing of the rows it came from.  Two things break that:

  * a subtitle row routinely holds the end of one sentence and the start of the
    next — "die eine Seite der Medaille. Kaum jemand fragt:" — so two
    sentences would claim the same cue and overlap on screen;
  * the model fixes words, drops stage directions and repunctuates, so the
    corrected text is not a substring of the original.

Both are handled by aligning at the word level.  Every word of the original is
given a time, the corrected words are matched against them with a sequence
matcher — which tolerates the edits, since most words survive a correction —
and each sentence takes the span of the original words it matched.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from alignment.timing import Timing, TimedWord
from corpus.sentence import RawLine, Sentence

WORD = re.compile(r"\w+", re.UNICODE)


class SubtitleAligner:
    """Gives each corrected sentence a `Timing` drawn from the original rows."""

    def align(self, lines: list[RawLine], sentences: list[Sentence]) -> list[Sentence]:
        if not lines or not sentences:
            return sentences
        timed = self._timed_words(lines)
        if not timed:
            return sentences

        spoken = [self._key(word.text) for word in timed]
        written, owners = self._corrected_words(sentences)
        spans = self._match(spoken, written, owners, len(sentences))

        video_id = lines[0].video_id
        return [
            self._apply(sentence, spans.get(index), timed, lines, video_id)
            for index, sentence in enumerate(sentences)
        ]

    # --- the original, word by word --------------------------------------

    @staticmethod
    def _timed_words(lines: list[RawLine]) -> list[TimedWord]:
        """Share each row's duration among its words, by their length."""
        out: list[TimedWord] = []
        for line in lines:
            words = WORD.findall(line.content)
            if not words:
                continue
            total = sum(len(word) for word in words)
            cursor = line.start_time
            for word in words:
                share = line.duration * (len(word) / total) if total else 0.0
                out.append(TimedWord(word, cursor, cursor + share))
                cursor += share
        return out

    @staticmethod
    def _corrected_words(sentences: list[Sentence]) -> tuple[list[str], list[int]]:
        """Every corrected word, and which sentence each belongs to."""
        written: list[str] = []
        owners: list[int] = []
        for index, sentence in enumerate(sentences):
            for word in WORD.findall(sentence.text):
                written.append(SubtitleAligner._key(word))
                owners.append(index)
        return written, owners

    # --- matching --------------------------------------------------------

    @staticmethod
    def _match(spoken, written, owners, count) -> dict[int, tuple[float, float]]:
        """Sentence index -> the range of original words it matched.

        `autojunk` is off: it discards items appearing in more than 1% of a
        long sequence, which for German would throw away `der`, `die` and
        `und` — exactly the anchors that hold an alignment together.
        """
        matcher = SequenceMatcher(None, spoken, written, autojunk=False)
        reach: dict[int, list[int]] = {}
        for source, target, size in matcher.get_matching_blocks():
            for offset in range(size):
                sentence = owners[target + offset]
                reach.setdefault(sentence, []).append(source + offset)
        return {
            index: (min(positions), max(positions))
            for index, positions in reach.items()
            if positions
        }

    @staticmethod
    def _apply(sentence, span, timed, lines, video_id) -> Sentence:
        """Attach a timing, falling back to the rows the model named.

        A sentence can match nothing — the model may have rewritten it past
        recognition, or invented it — and a cue is still better than none, so
        the declared source rows stand in.
        """
        if span is not None:
            start, end = timed[span[0]].start, timed[span[1]].end
        else:
            sources = [x for x in lines if x.sentence_id in sentence.source_ids]
            if not sources:
                return sentence
            start = min(x.start_time for x in sources)
            end = max(x.start_time + x.duration for x in sources)
        return sentence.with_timing(Timing(video_id, start, max(end, start)))

    @staticmethod
    def _key(word: str) -> str:
        return word.lower()
