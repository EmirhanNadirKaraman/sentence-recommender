"""Surface forms -> the lemmas that actually appear in the corpus.

This is the step that makes i+1 meaningful.  `word_table` stores one row per
*surface* (`wird`, `wurde`, `geworden` are three rows) but the vocabulary
files list dictionary forms.  Counting unknowns over surfaces would leave
almost every sentence looking unreadable, so both sides are collapsed to
`word_table.lemma`.
"""
from __future__ import annotations

from vocab.entry import Unit


class VocabResolver:
    """Turns a word list into a set of `Unit`s the corpus can be scored against."""

    def __init__(self, words) -> None:      # words: WordRepository
        self._words = words

    def lemmas(self, surfaces: list[str]) -> set[str]:
        """Every corpus lemma reachable from `surfaces`.

        A surface resolves if it matches either a stored surface form
        (`word_norm`, the ICU-normalised generated column) or a stored lemma
        directly — the vocabulary files mix both.
        """
        if not surfaces:
            return set()
        return self._words.lemmas_for_surfaces(surfaces)

    def units(self, surfaces: list[str]) -> set[Unit]:
        return {Unit.lemma(lemma) for lemma in self.lemmas(surfaces)}
