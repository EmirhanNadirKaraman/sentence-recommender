"""Wiring.

One place that knows how the pieces fit together, so the command classes stay
about what they do rather than how everything is constructed.  Everything is
lazy — a review session should not open a Postgres connection or load spaCy
just to read cached cards.
"""
from __future__ import annotations

from functools import cached_property

from config import Settings
from corpus import CorpusStore, SentenceFilter, SentenceOverrides, UnitAnalyzer
from db import Database, PatternRepository, WordRepository
from roadmap import ExampleIndex, KnownSet, UnitPriority
from srs import CardStore, PromptBuilder, SM2Scheduler
from vocab import GoalList, KnownStore, Unit, WordListLoader


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

    def filter(self, min_words: int | None = None) -> SentenceFilter:
        return SentenceFilter(
            min_words or self.settings.min_tokens, self.settings.max_tokens
        )

    @cached_property
    def overrides(self) -> SentenceOverrides:
        return SentenceOverrides(self.settings.state_path)

    def corpus(self, *builds: str, teachable_only: bool = True,
               list_only: bool = False):
        """Cached sentences from the named builds, with reader corrections.

        Corrections are applied on the way out rather than baked into the
        cache, so rebuilding the corpus cannot lose them.

        `list_only` narrows every sentence to the units on the study list.
        The analyser finds more than the list names — a noun yields both a
        bare lemma and its article form, so `Kugel` arrives as both `kugel`
        and `die Kugel` and has to be learned twice. Counting only what the
        list names removes the duplicate and, because it removes unknowns
        too, turns sentences that were two or three away into i+1.

        The trade is real: a sentence can then be called readable while
        holding a word you do not know, because that word was never
        something you set out to learn.
        """
        sentences = self._apply_overrides(self.corpus_store.load(
            *(builds or self.corpus_store.builds()), teachable_only=teachable_only
        ))
        return self._narrow_to_list(sentences) if list_only else sentences

    def _narrow_to_list(self, sentences: list) -> list:
        goals = frozenset(self.goal_units)
        return [
            s.with_units(
                s.units & goals,
                tuple((u, x) for u, x in s.surfaces if u in goals),
            )
            for s in sentences
        ]

    def _apply_overrides(self, sentences: list) -> list:
        hidden = self.overrides.hidden()
        corrected = self.overrides.corrected()
        if not hidden and not corrected:
            return sentences
        out = []
        for sentence in sentences:
            if sentence.text in hidden:
                continue
            fix = corrected.get(sentence.text)
            if fix is not None:
                sentence = sentence.with_units(
                    frozenset(fix),
                    tuple((unit, surface) for unit, surface in fix.items() if surface),
                )
            out.append(sentence)
        return out

    def example_index(self, *builds: str) -> ExampleIndex:
        return ExampleIndex(self.corpus(*builds))

    def prompts(self, *builds: str) -> PromptBuilder:
        return PromptBuilder(
            self.example_index(*builds), self.settings.examples_per_card
        )

    # --- vocabulary ------------------------------------------------------

    @cached_property
    def marked_known(self) -> KnownStore:
        return KnownStore(self.settings.state_path)

    def known_set(self) -> KnownSet:
        """Everything the reader knows: the vocabulary files plus what they
        have marked while reading.

        Resolved twice on purpose.  The corpus is lemmatised by spaCy, so the
        vocabulary has to land in *that* lemma space or a known word will not
        match its own occurrences; `word_table` is consulted as well because it
        covers surface forms spaCy lemmatises differently in isolation.
        """
        surfaces = self._surfaces()
        with Database(self.settings.database) as db:
            lemmas = WordRepository(db, self.settings.language).lemmas_for_surfaces(surfaces)
        lemmas |= self.analyzer.lemmas(surfaces)
        return KnownSet(
            {Unit.lemma(lemma) for lemma in lemmas} | self.marked_known.units()
        )

    @cached_property
    def goal_units(self) -> tuple[Unit, ...]:
        """The list you mean to learn, in the order it was written.

        Serves twice over: as the destination when building towards a list,
        and as the teaching-order ranking otherwise. One authored ordering
        covering both words and patterns is what lets the two be compared at
        all — see `roadmap.priority`.
        """
        with Database(self.settings.database) as db:
            patterns = PatternRepository(db, self.settings.language).canonicals()
        return GoalList(self.settings.goal_words).units(patterns)

    def priority(self) -> UnitPriority:
        return UnitPriority.build(self.goal_units)

    def _surfaces(self) -> list[str]:
        loader = WordListLoader()
        surfaces: list[str] = []
        for path in (self.settings.known_words, self.settings.function_words):
            if path.exists():
                surfaces.extend(loader.load(path).surfaces)
        return surfaces
