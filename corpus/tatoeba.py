"""The Tatoeba German-English corpus.

Human-written sentences with human translations — 276k German sentences
paired to English, median six tokens.  Beside them the subtitle corpus is
both small and rough, so this is the primary source of examples.

Read from a local export in three tab-separated columns

    sentence_id <TAB> language <TAB> text

plus a link file pairing sentence ids across languages.  Nothing is
downloaded; point `TatoebaSource` at whichever export you have.
"""
from __future__ import annotations

import csv
from pathlib import Path

from corpus.sentence import TATOEBA, Sentence


class TatoebaSource:
    """German sentences that have an English translation, de-duplicated."""

    def __init__(
        self,
        sentences_path: Path,
        links_path: Path,
        language: str = "deu",
        translation_language: str = "eng",
    ) -> None:
        self._sentences_path = sentences_path
        self._links_path = links_path
        self._language = language
        self._translation_language = translation_language

    def sentences(self) -> list[Sentence]:
        source, target = self._read_sentences()
        seen: set[str] = set()
        out: list[Sentence] = []
        for source_id, target_id in self._read_links():
            text = source.get(source_id)
            translation = target.get(target_id)
            if text is None or translation is None or text in seen:
                continue
            seen.add(text)
            out.append(Sentence(text=text, origin=TATOEBA, translation=translation))
        return out

    def _read_sentences(self) -> tuple[dict[str, str], dict[str, str]]:
        source: dict[str, str] = {}
        target: dict[str, str] = {}
        for row in self._rows(self._sentences_path, columns=3):
            sentence_id, language, text = row[0], row[1], row[2]
            if language == self._language:
                source[sentence_id] = text
            elif language == self._translation_language:
                target[sentence_id] = text
        return source, target

    def _read_links(self):
        for row in self._rows(self._links_path, columns=2):
            yield row[0], row[1]

    @staticmethod
    def _rows(path: Path, columns: int):
        with path.open(encoding="utf-8", newline="") as handle:
            # QUOTE_NONE: the exports contain bare quote characters inside
            # sentence text, which csv would otherwise swallow.
            for row in csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
                if len(row) >= columns:
                    yield row
