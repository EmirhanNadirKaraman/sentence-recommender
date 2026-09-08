"""Wiring.

One place that knows how the pieces fit together, so the command classes stay
about what they do rather than how everything is constructed.  Everything is
lazy — a review session should not open a Postgres connection or load spaCy
just to read cached cards.
"""
from __future__ import annotations

from functools import cached_property

from config import Settings
from corpus import CorpusStore, SentenceFilter, UnitAnalyzer
from db import Database, PatternRepository, WordRepository
from roadmap import ExampleIndex, KnownSet
from srs import CardStore, PromptBuilder, SM2Scheduler
from vocab import Unit, WordListLoader


class Application:
    """Lazily constructed object graph, shared by every command."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    # --- storage ---------------------------------------------------------

    @cached_property
    def corpus_store(self) -> CorpusStore:
        return CorpusStore(self.settings.state_path)

    @cached_property
    def card_store(self) -> CardStore:
        return CardStore(self.settings.state_path)

    @cached_property
    def scheduler(self) -> SM2Scheduler:
        return SM2Scheduler()

    # --- corpus ----------------------------------------------------------

    @cached_property
    def analyzer(self) -> UnitAnalyzer:
        with Database(self.settings.database) as db:
            patterns = PatternRepository(db, self.settings.language).canonicals()
        return UnitAnalyzer(
            patterns, self.settings.language, self.settings.analysis_processes
        )

    def filter(self) -> SentenceFilter:
        return SentenceFilter(self.settings.min_tokens, self.settings.max_tokens)

    def corpus(self, *builds: str, teachable_only: bool = True):
        """Cached sentences from the named builds, or from all of them."""
        return self.corpus_store.load(
            *(builds or self.corpus_store.builds()), teachable_only=teachable_only
        )

    def example_index(self, *builds: str) -> ExampleIndex:
        return ExampleIndex(self.corpus(*builds))

    def prompts(self, *builds: str) -> PromptBuilder:
        return PromptBuilder(
            self.example_index(*builds), self.settings.examples_per_card
        )

    # --- vocabulary ------------------------------------------------------

    def known_set(self) -> KnownSet:
        """The starting known set: the two vocabulary files, resolved to lemmas.

        Resolved twice on purpose.  The corpus is lemmatised by spaCy, so the
        vocabulary has to land in *that* lemma space or a known word will not
        match its own occurrences; `word_table` is consulted as well because it
        covers surface forms spaCy lemmatises differently in isolation.
        """
        surfaces = self._surfaces()
        with Database(self.settings.database) as db:
            lemmas = WordRepository(db, self.settings.language).lemmas_for_surfaces(surfaces)
        lemmas |= self.analyzer.lemmas(surfaces)
        return KnownSet(Unit.lemma(lemma) for lemma in lemmas)

    def priority_surfaces(self) -> list[str]:
        """The frequency-ordered word list that ranks what to teach next."""
        return list(WordListLoader().load(self.settings.priority_words).surfaces)

    def _surfaces(self) -> list[str]:
        loader = WordListLoader()
        surfaces: list[str] = []
        for path in (self.settings.known_words, self.settings.function_words):
            if path.exists():
                surfaces.extend(loader.load(path).surfaces)
        return surfaces
