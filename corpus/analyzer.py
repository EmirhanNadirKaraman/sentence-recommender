"""Deriving a sentence's learning units by running the matcher over it.

Units come from the *corrected* text, not from the `word_to_sentence` bridge.
That bridge is keyed to the raw subtitle rows, so once a sentence has been
reassembled or repunctuated it no longer describes what the learner reads.
Running the matcher live keeps the units and the displayed sentence in step —
and it is the same matcher that produced the bridge in the first place.

Two kinds come out:
  lemma   — content words, from spaCy's lemmatiser
  pattern — a `phrase_table.canonical`, e.g. "jdm. (Dat) etw. (Akk) geben",
            kept only when the matcher's blueprint is a registered pattern
            rather than a plain dictionary look-up
"""
from __future__ import annotations

import sys
from pathlib import Path

from corpus.sentence import Sentence
from db.word_repo import FREE_TAGS, PUNCTUATION_TAGS
from vocab.entry import Unit

_MATCHER_DIR = Path(__file__).resolve().parents[1] / "matcher"


class UnitAnalyzer:
    """Wraps the vendored matcher.  spaCy loads on first use, not on import."""

    def __init__(
        self,
        pattern_vocabulary: frozenset[str],
        language: str = "de",
        processes: int = 1,
    ) -> None:
        self._patterns = pattern_vocabulary
        self._language = language
        self._processes = processes
        self._matcher = None

    @property
    def matcher(self):
        if self._matcher is None:
            if str(_MATCHER_DIR) not in sys.path:
                sys.path.insert(0, str(_MATCHER_DIR))
            import phrase_finder            # noqa: PLC0415 — deferred, loads spaCy
            self._matcher = phrase_finder
        return self._matcher

    def analyze_all(self, sentences: list[Sentence]) -> list[Sentence]:
        """Attach units to every sentence, parsing in one batched pass.

        `processes` > 1 forks spaCy workers for the parse, which is the
        expensive half; pattern extraction stays in this process because it
        walks the parsed Doc.  Worth it only for the full corpus — for a
        handful of sentences the fork cost dominates.
        """
        docs = self.matcher.nlp.pipe(
            [s.text for s in sentences],
            batch_size=500,
            n_process=self._processes if len(sentences) > 5_000 else 1,
        )
        return [s.with_units(*self._units(doc)) for s, doc in zip(sentences, docs)]

    def lemmas(self, texts: list[str]) -> set[str]:
        """Lemmatise arbitrary text with the same model the corpus was parsed by.

        Used to resolve the vocabulary files into the corpus's own lemma space,
        so a known word and its corpus occurrences cannot disagree.
        """
        out: set[str] = set()
        for doc in self.matcher.nlp.pipe(texts, batch_size=256):
            out.update(
                token.lemma_.lower() for token in doc if self._is_content(token)
            )
        return out

    def _units(self, doc) -> tuple[frozenset[Unit], tuple[tuple[Unit, str], ...]]:
        units: set[Unit] = set()
        surfaces: dict[Unit, str] = {}
        for token in doc:
            if not self._is_content(token):
                continue
            unit = Unit.lemma(token.lemma_)
            units.add(unit)
            surfaces.setdefault(unit, token.text)
        for phrase in self.matcher.extract_phrases(doc, self._language):
            entry = phrase["dictionary_entry"]
            if entry in self._patterns:
                unit = Unit.pattern(entry)
                units.add(unit)
                surfaces.setdefault(unit, " ".join(phrase["sentence_phrase"]))
        return frozenset(units), tuple(surfaces.items())

    @staticmethod
    def _is_content(token) -> bool:
        """Punctuation is not vocabulary; names and numbers are free.

        A proper noun or a numeral in a sentence does not make it harder to
        read — you do not need to have learned "Dresden" to understand a
        sentence containing it — so neither counts toward the unknown tally.
        """
        if token.is_punct or token.is_space:
            return False
        if token.tag_ in PUNCTUATION_TAGS or token.tag_ in FREE_TAGS:
            return False
        return bool(token.lemma_.strip()) and token.lemma_ != "--"
