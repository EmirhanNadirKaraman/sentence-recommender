"""Sentences from written transcripts, where there is no video to align to.

The subtitle path exists because a subtitle is not a sentence: it is a cue of
a second or two, cut wherever the line filled up, and `alignment` puts the
pieces back together using the timings. A transcript has the same problem
without the timings — it is wrapped to a column width, so a sentence runs
across two or three lines — and none of that machinery applies.

What it has instead is punctuation, which subtitles largely lack. Lines are
joined until one ends a sentence, and that is the sentence.

Two layouts, told apart by reading the file rather than by trusting its name:

  bilingual     German and English on alternating lines, line for line. The
                English travels with the German as its translation — the
                reading page has had a field for that since the beginning and
                nothing to put in it.
  single        German throughout, wrapped.

The pairing is kept line by line rather than by joining each language and
splitting both, because the two do not split into the same number of
sentences: German runs several clauses into one where English stops, and one
mismatch would shift every translation after it by one.
"""
from __future__ import annotations

import re
from pathlib import Path

from corpus.sentence import TRANSCRIPT, Sentence

# Enough of the commonest closed-class words to tell the two languages apart
# on a single line. Content words are no use — a German line about philosophy
# and an English one about philosophy share most of them.
GERMAN = re.compile(r"\b(ich|und|das|nicht|ist|die|der|wir|auch|sehr|aber|mit"
                    r"|für|sich|noch|schon|wenn|dass|man)\b", re.IGNORECASE)
ENGLISH = re.compile(r"\b(the|and|is|you|that|with|for|have|this|are|was|were"
                     r"|they|there|about|would)\b", re.IGNORECASE)
ENDS = re.compile(r"[.!?…]['\"»)\]]?$")


def language(line: str) -> str:
    """Which language a line is in, by counting function words."""
    de, en = len(GERMAN.findall(line)), len(ENGLISH.findall(line))
    return "de" if de > en else "en" if en > de else "?"


class TranscriptSource:
    """Every transcript under a folder, as sentences."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def files(self) -> list[Path]:
        return sorted(self._root.rglob("*.txt"))

    def sentences(self) -> list[Sentence]:
        out: list[Sentence] = []
        for path in self.files():
            out.extend(self.read(path))
        return out

    @classmethod
    def read(cls, path: Path) -> list[Sentence]:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        # `\r` is a line break here, not a carriage return paired with one:
        # these files carry `\n\r\n` runs, so splitting on `\n` alone leaves
        # every other line holding a lone `\r`.
        lines = [line.strip() for line in raw.replace("\r", "\n").split("\n")]
        lines = [line for line in lines if line]
        if not lines:
            return []
        pairs = cls._pair(lines)
        return [s for s in (cls._sentence(de, en, path) for de, en in pairs) if s]

    @staticmethod
    def _alternates(lines: list[str]) -> bool:
        """Whether the file runs German and English on alternating lines.

        Read from the text, not from the filename. Most of the bilingual ones
        are unmarked and most of the single-language ones say `German only`,
        but the naming is inconsistent enough that a file would be silently
        mangled — every second line dropped as a translation, or an English
        line taught as German.
        """
        tags = [language(line) for line in lines[:40]]
        paired = sum(1 for i in range(0, len(tags) - 1, 2)
                     if tags[i] == "de" and tags[i + 1] == "en")
        return paired > len(tags) / 4

    @classmethod
    def _pair(cls, lines: list[str]) -> list[tuple[list[str], list[str]]]:
        """Group wrapped lines into sentences, carrying any translation."""
        bilingual = cls._alternates(lines)
        out: list[tuple[list[str], list[str]]] = []
        de: list[str] = []
        en: list[str] = []
        step = 2 if bilingual else 1
        for i in range(0, len(lines), step):
            de.append(lines[i])
            if bilingual and i + 1 < len(lines):
                en.append(lines[i + 1])
            if ENDS.search(lines[i]):
                out.append((de, en))
                de, en = [], []
        if de:
            out.append((de, en))
        return out

    @staticmethod
    def _sentence(de: list[str], en: list[str], path: Path) -> Sentence | None:
        text = " ".join(de).strip()
        if not text:
            return None
        return Sentence(
            text=text,
            origin=TRANSCRIPT,
            translation=" ".join(en).strip() or None,
        )
