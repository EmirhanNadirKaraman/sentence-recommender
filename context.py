"""Wiring.

One place that knows how the pieces fit together, so the command classes stay
about what they do rather than how everything is constructed.  Everything is
lazy — a review session should not open a Postgres connection or load spaCy
just to read cached cards.
"""
from __future__ import annotations

import re
import sys
from functools import cached_property

from config import Settings
from corpus import CorpusStore, SentenceFilter, SentenceOverrides, UnitAnalyzer
from db import Database, PatternRepository, WordRepository
from roadmap import ExampleIndex, KnownSet, UnitPriority
from srs import CardStore, PromptBuilder, SM2Scheduler
from vocab import (CheckedStore, GoalList, KnownStore, SnoozeStore, Unit,
                   WordListLoader)
from vocab.cache import ResolvedCache


class Application:
    """Lazily constructed object graph, shared by every command."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    # --- storage ---------------------------------------------------------

    @cached_property
    def corpus_store(self) -> CorpusStore:
        return CorpusStore(self.settings.state_path,
                           self.settings.ignored_builds)

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
    def video_minutes(self) -> dict[str, float]:
        """How long each video runs, in minutes.

        Here rather than beside either caller, because both the walk and the
        pages that score videos want the same answer and a second copy is how
        two rankings drift apart.
        """
        with Database(self.settings.database) as db:
            rows = db.rows("SELECT video_id, duration FROM video"
                           " WHERE duration IS NOT NULL")
        return {video: seconds / 60 for video, seconds in rows}

    @cached_property
    def overrides(self) -> SentenceOverrides:
        return SentenceOverrides(self.settings.state_path)

    def corpus(self, *builds: str, teachable_only: bool = True,
               list_only: bool = False, strict: bool = False,
               holding: tuple[str, str] | None = None,
               text: str | None = None):
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

        `strict` is the answer to that, and supersedes `list_only` rather
        than combining with it. It keeps every word in the sentence and drops
        only the ones the list already teaches under another name — `Kugel`
        arriving a second time as a bare `kugel` — so a word you genuinely do
        not know still counts against the sentence. See `covered_forms` for
        which is which.
        """
        self.check_freshness()
        # `holding` asks for the sentences saying one word. A page that wants
        # twenty-five of them has no business materialising a hundred and
        # fifteen thousand, which is what it did before the index existed.
        sentences = self.apply_overrides(self.corpus_store.load(
            *(builds or self.corpus_store.builds()),
            teachable_only=teachable_only, holding=holding, text=text,
        ))
        if strict:
            return self._drop_duplicates(sentences)
        return self._narrow_to_list(sentences) if list_only else sentences

    @cached_property
    def check_freshness(self):
        """Say so when a cached build was made by rules that have changed.

        Checked once per process and reported once. The alternative is what
        this project did for a whole session: a page that looked right, was
        not, and had nothing to indicate which.
        """
        for build, made_with in self.corpus_store.stale().items():
            source = build.split(":")[0]
            print(f"warning: corpus '{build}' was analysed by different rules "
                  f"(fingerprint {made_with}) — rebuild it with "
                  f"`python main.py build-corpus {source}`", file=sys.stderr)
        return lambda: None

    # Bits of a pattern that name a role rather than a word. Without these
    # out of the way, `etw.` and `jdm.` would count as vocabulary the list
    # teaches, and every sentence containing them would look covered.
    PLACEHOLDERS = frozenset({
        "jdm", "jdn", "etw", "dat", "akk", "gen", "sich", "der", "die", "das",
        "ein", "eine", "einer", "einem", "einen", "zu", "an", "auf", "in",
        "mit", "von", "bei", "um", "vor", "nach", "aus", "über",
    })

    @cached_property
    def covered_forms(self) -> frozenset[str]:
        """Every word the study list teaches, under whatever name it uses.

        The list writes a noun with its article and a verb inside a pattern —
        `die Schule`, `jdm. (Dat) etw. (Akk) erzählen` — while the analyser
        also yields the bare lemma, `schule` and `erzählen`. Those are one
        word arriving twice, which is the duplicate `list_only` exists to
        collapse.

        Narrowing collapses it by throwing away everything off the list, and
        with it the difference between a duplicate and a word you genuinely
        do not know. Strict counting needs that difference back, so it keeps
        the forms rather than the units: `passieren` beside the goal that
        teaches it is not a gap, and `Ministerin` is.

        Read off the written keys rather than lemmatised, which would cost a
        parser to resolve what the list almost always already writes in lemma
        form. The cost of the exceptions is a word counted as a stranger that
        the list does in fact reach — the safe direction, since it only ever
        holds a sentence back.
        """
        words: set[str] = set()
        for unit in self.goal_units:
            for word in re.findall(r"[^\W\d_]+", unit.key.lower()):
                if len(word) > 2 and word not in self.PLACEHOLDERS:
                    words.add(word)
        return frozenset(words)

    def _drop_duplicates(self, sentences: list) -> list:
        """Every sentence, less the units the list already teaches elsewhere.

        What is left is what strict counting wants: the goals, the words
        already known, and the genuine strangers — words neither known nor on
        the list, which the walk will never teach and which therefore keep a
        sentence out of an i+1 reading for good.
        """
        goals = frozenset(self.goal_units)
        covered = self.covered_forms

        def keep(unit) -> bool:
            return unit in goals or unit.key.lower() not in covered

        return [
            s.with_units(
                frozenset(u for u in s.units if keep(u)),
                tuple((u, x) for u, x in s.surfaces if keep(u)),
            )
            for s in sentences
        ]

    def _narrow_to_list(self, sentences: list) -> list:
        goals = frozenset(self.goal_units)
        return [
            s.with_units(
                s.units & goals,
                tuple((u, x) for u, x in s.surfaces if u in goals),
            )
            for s in sentences
        ]

    def apply_overrides(self, sentences: list) -> list:
        """What the reader has said about particular sentences, applied.

        Public because the reading page needs it too: a deck stored with a
        roadmap step predates every correction made since, and the two buttons
        under each slide have to reach it somehow. Both are a query against
        the overrides rather than anything to do with a corpus, so they can be
        applied to stored sentences on the way out.
        """
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
    def resolved(self) -> ResolvedCache:
        return ResolvedCache(self.settings.state_path)

    @cached_property
    def marked_known(self) -> KnownStore:
        return KnownStore(self.settings.state_path)

    @cached_property
    def snoozes(self) -> SnoozeStore:
        return SnoozeStore(self.settings.state_path)

    @cached_property
    def checked(self) -> CheckedStore:
        return CheckedStore(self.settings.state_path)

    def known_set(self) -> KnownSet:
        """Everything the reader knows: the vocabulary files plus what they
        have marked while reading.

        Resolved twice on purpose.  The corpus is lemmatised by spaCy, so the
        vocabulary has to land in *that* lemma space or a known word will not
        match its own occurrences; `word_table` is consulted as well because it
        covers surface forms spaCy lemmatises differently in isolation.
        """
        return KnownSet(
            {Unit.lemma(lemma) for lemma in self._known_lemmas()}
            | self.marked_known.units()
        )

    def _known_lemmas(self) -> list[str]:
        """The vocabulary files as lemmas, from cache when it still applies.

        Only the files are cached. What the reader has marked known while
        reading is added on top every time, because that changes constantly
        and costs nothing to read.
        """
        files = [self.settings.known_words, self.settings.function_words]
        cached = self.resolved.get("known", files)
        if cached is not None:
            return cached
        surfaces = self._surfaces()
        with Database(self.settings.database) as db:
            lemmas = WordRepository(db, self.settings.language).lemmas_for_surfaces(surfaces)
        lemmas |= self.analyzer.lemmas(surfaces)
        out = sorted(lemmas)
        self.resolved.put("known", files, out)
        return out

    @cached_property
    def goal_units(self) -> tuple[Unit, ...]:
        """The list you mean to learn, in the order it was written.

        Serves twice over: as the destination when building towards a list,
        and as the teaching-order ranking otherwise. One authored ordering
        covering both words and patterns is what lets the two be compared at
        all — see `roadmap.priority`.
        """
        # Both files stamp the cache: a correction added to `goal_lemmas`
        # has to invalidate it, or editing the file would appear to do
        # nothing at all.
        files = [self.settings.goal_words, self.settings.goal_lemmas]
        cached = self.resolved.get("goals", files)
        if cached is not None:
            return tuple(Unit(kind, key) for kind, key in cached)
        with Database(self.settings.database) as db:
            patterns = PatternRepository(db, self.settings.language).canonicals()
        units = GoalList(self.settings.goal_words).units(
            patterns, self.analyzer.lemmatise_each,
            GoalList.corrections(self.settings.goal_lemmas),
        )
        self.resolved.put("goals", files, [[u.kind, u.key] for u in units])
        return units

    def priority(self) -> UnitPriority:
        return UnitPriority.build(self.goal_units)

    def _surfaces(self) -> list[str]:
        loader = WordListLoader()
        surfaces: list[str] = []
        for path in (self.settings.known_words, self.settings.function_words):
            if path.exists():
                surfaces.extend(loader.load(path).surfaces)
        return surfaces
