"""Wiring.

One place that knows how the pieces fit together, so the command classes stay
about what they do rather than how everything is constructed.  Everything is
lazy — a review session should not open a Postgres connection or load spaCy
just to read cached cards.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from functools import cached_property

from config import Settings
from corpus import CorpusStore, SentenceFilter, SentenceOverrides, UnitAnalyzer
from db import Database, PatternRepository, WordRepository
from roadmap import ExampleIndex, KnownSet, UnitPriority
from srs import CardStore, PromptBuilder, SM2Scheduler
from vocab import (CheckedStore, GoalList, KnownStore, SnoozeStore, Unit,
                   WordListLoader)
from vocab.cache import ResolvedCache
from vocab.aliases import Aliases
from vocab.compounds import Compounds


class Application:
    """Lazily constructed object graph, shared by every command."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        # (blacklist version, the videos it removes) -- see `banned_videos`.
        self._banned: tuple[int, frozenset[str]] | None = None

    # --- storage ---------------------------------------------------------

    @cached_property
    def corpus_store(self) -> CorpusStore:
        return CorpusStore(self.settings.own,
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
        with Database(self.settings.own) as db:
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
        with Database(self.settings.own) as db:
            rows = db.rows("SELECT video_id, duration FROM video"
                           " WHERE duration IS NOT NULL")
        return {video: seconds / 60 for video, seconds in rows}

    @cached_property
    def overrides(self) -> SentenceOverrides:
        return SentenceOverrides(self.settings.state_path)

    @cached_property
    def answers(self):
        """What the corpus pass's judge said about sentences and their words."""
        from corpus.answers import AnswerStore              # noqa: PLC0415
        return AnswerStore(self.settings.state_path)

    @cached_property
    def judged(self):
        """The judge's answers as `rank` reads them, loaded once per process.

        The same bargain as `verdicts`: passed to every ranking rather than
        looked up by some, so the walk and the pages order alike.
        """
        from corpus.questions import VERSION                # noqa: PLC0415
        return self.answers.load(self.settings.judge_model, VERSION)

    @cached_property
    def blacklist(self):
        """The channels the reader has removed. See `vocab.channel_taste`."""
        from vocab.channel_taste import ChannelBlacklist   # noqa: PLC0415
        return ChannelBlacklist(self.settings.state_path)

    def banned_videos(self) -> frozenset[str]:
        """Every video of a removed channel -- what the blacklist means in
        the terms the corpus speaks.

        Derived once per change rather than per call: the channel-to-video
        map is a catalogue query, and this is asked on every corpus load.
        The blacklist's version says whether the last answer still stands,
        so a page never carries a channel the reader has just restored.
        """
        version = self.blacklist.version()
        if self._banned is None or self._banned[0] != version:
            channels = list(self.blacklist.all())
            videos: frozenset[str] = frozenset()
            if channels:
                with Database(self.settings.own) as db:
                    videos = frozenset(video for (video,) in db.rows(
                        "SELECT v.video_id FROM video v"
                        " JOIN channel c ON c.id = v.channel_id"
                        " WHERE c.youtube_channel_id = ANY(%s)", (channels,)))
            self._banned = (version, videos)
        return self._banned[1]

    @cached_property
    def glosses(self):
        """What the model has said in English about sentences and words."""
        from deck.gloss import GlossStore                   # noqa: PLC0415
        return GlossStore(self.settings.state_path)

    @property
    def llm_model(self) -> str:
        """The configured model's name, which keys everything it has said."""
        import os                                           # noqa: PLC0415
        return os.environ.get("LLM_MODEL", "")

    def with_english(self, sentences) -> list:
        """Sentences as a reader should see them: with the model's English.

        Every screen that shows a sentence goes through here, so a
        translation that exists anywhere is shown everywhere -- the
        roadmap, a unit's examples, the reading deck, a video's transcript,
        the terminal review -- and not only on the cards the deck commands
        assemble.
        """
        found = self.glosses.translated(
            [s for s in sentences if s is not None], self.llm_model)
        it = iter(found)
        return [None if s is None else next(it) for s in sentences]

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
        than combining with it. It keeps every word in the sentence and
        *renames* the ones the list already teaches under another name —
        `Kugel` arriving a second time as a bare `kugel` becomes the goal
        `die Kugel` — so the duplicate collapses without the word leaving the
        sentence. See `Aliases`, and the bug that comes of deleting it
        instead.
        """
        self.check_freshness()
        # Decided once and applied while the units are read, rather than by a
        # pass over the finished sentences — see `_unit_rule`.
        resolve = self._unit_rule(strict, list_only)
        # `holding` asks for the sentences saying one word. A page that wants
        # twenty-five of them has no business materialising a hundred and
        # fifteen thousand, which is what it did before the index existed.
        return self.apply_overrides(self.corpus_store.load(
            *(builds or self.corpus_store.builds()),
            teachable_only=teachable_only, holding=holding, text=text,
            resolve=resolve,
        ), resolve)

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
    # `dat`, `akk` and `gen` are deliberately absent: they are case markers
    # and only ever appear parenthesised — `jds. (Gen) gedenken` — so they
    # are removed by stripping the parentheses instead. Listing them here as
    # bare words made `das Gen` strip its own noun, so the goal was blocked
    # by `gen`, the lemma of the very word it teaches. A reader saw it on the
    # page: "needs 1 other new word here: gen".
    PLACEHOLDERS = frozenset({
        "jdm", "jdn", "etw", "sich", "der", "die", "das",
        "ein", "eine", "einer", "einem", "einen", "zu", "an", "auf", "in",
        "mit", "von", "bei", "um", "vor", "nach", "aus", "über",
        # Preposition-article contractions. They belong here for the same
        # reason the prepositions above do — `im Jahr` names a role, and `im`
        # is not vocabulary the list teaches. They used to be excluded by a
        # `len(word) > 2` guard, which also discarded `Öl` and `CD`: ordinary
        # nouns, blocked by their own bare lemma because the goal never
        # covered it.
        "im", "am", "beim", "zum", "zur", "vom", "ins", "ans", "aufs",
        "fürs", "durchs", "ums", "übers", "unterm", "hinterm",
    })

    @cached_property
    def covered_forms(self) -> frozenset[str]:
        """Every word the study list teaches, under whatever name it uses.

        The set of `covered_by`'s keys. Kept as its own name because most
        callers only ask whether a form is covered, not by what.
        """
        return frozenset(self.covered_by)

    @cached_property
    def covered_by(self) -> dict[str, frozenset[Unit]]:
        """Which goal unit teaches each form, for the callers that need it.

        `covered_forms` answers "is this word already on the list". Compounds
        need the other half: a compound part written `haus` is taught by the
        goal `das Haus`, and under strict counting the bare form is renamed to
        that goal in every sentence. Resolving the part to the form alone
        found nothing
        -- 187 of 231 parts vanish that way, and the whole list granted two
        compounds instead of a hundred and eighty.

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
        out: dict[str, set[Unit]] = defaultdict(set)
        for unit in self.goal_units:
            # Both cases, and the pair is the point. Lemma keys are lowercase
            # except the nouns that share one with a verb, which keep a
            # capital — so `das Unternehmen` has to cover `Unternehmen` the
            # noun as well as `unternehmen`, or the goal is blocked by the
            # very word it exists to teach. Reading the written case alone
            # would be worse: `das Jahr` would then cover `Jahr` and not
            # `jahr`, and every article-and-noun goal on the list would break
            # the same way.
            #
            # What this does not do is cover a capital the goal never wrote.
            # `jdn. (Akk) ... nennen` is lowercase throughout, so it covers
            # the verb and leaves any noun `Nennen` alone, which is the whole
            # distinction the split exists for.
            # Case markers first, as whole parenthesised groups, so a noun
            # that happens to spell one survives.
            written = re.sub(r"\([^)]*\)", " ", unit.key)
            # Hyphenated words are one word. `[^\W\d_]+` alone split
            # `die E-Mail` into `E` and `Mail`, so the lemma `e-mail` the
            # analyser produces was never covered and the goal was blocked by
            # its own bare form — 121 sentences saying it, none able to teach
            # it.
            for word in re.findall(r"[^\W\d_]+(?:-[^\W\d_]+)*", written):
                # Two letters, not three. `das Öl` and `die CD` are ordinary
                # nouns that the length guard discarded, with the same result.
                # Single letters stay out, which is what the guard was for —
                # and the particles it was also catching are named explicitly
                # in PLACEHOLDERS anyway.
                if len(word) >= 2 and word.lower() not in self.PLACEHOLDERS:
                    out[word].add(unit)
                    out[word.lower()].add(unit)
        return {form: frozenset(units) for form, units in out.items()}

    @cached_property
    def aliases(self) -> Aliases:
        """The list's own name for each word it teaches. See `Aliases`."""
        return Aliases(self.goal_units)

    def _unit_rule(self, strict: bool, list_only: bool):
        """What each unit counts as, applied while the units are read.

        Returns None when every unit counts as itself, so the common path
        pays nothing. Otherwise a function from a unit to the unit that
        should stand in its place, or to None to drop it.

        `strict` keeps every word in the sentence and renames the ones the
        list already teaches under another name — `Kugel` arriving a second
        time as a bare `kugel` becomes the goal `die Kugel` that teaches it.
        What is left is the goals, the words already known, and the genuine
        strangers: words neither known nor on the list, which the walk will
        never teach and which therefore keep a sentence out of an i+1 reading
        for good.

        It used to *delete* the duplicate rather than rename it, testing only
        whether the list taught that word somewhere — never whether the goal
        that teaches it was anywhere near. `die Technologie` is on the list,
        so `technologie` was struck out of every sentence in the corpus,
        including the ones that neither say the goal nor teach it. 31% of
        sentences lost a word with nothing standing in, and 1,206 of 3,910
        roadmap steps offered a sentence holding a word the reader had no way
        to have learned. Renaming collapses the same duplicate and leaves the
        word — as the goal, so the walk can still teach it.

        `list_only` keeps only what the list names. That removes the
        duplicate too, and removes unknowns with it, so sentences that were
        two or three away become i+1 — at the price of calling a sentence
        readable while it holds a word you do not know, because that word was
        never something you set out to learn.

        It renames before it drops, the same way strict does. It used to
        keep a unit only if it *was* a goal, which worked while every verb
        the list teaches arrived as its pattern in every sentence — and that
        stopped being so when the matcher stopped crediting `etw./jdn. (Akk)
        haben` to the perfect tense. `Ich habe das Buch gelesen` then carries
        `haben` only as the bare lemma, which is not a goal, and a filter on
        goals alone would call the sentence readable to someone who has
        never learned `haben`. Renaming the lemma to the goal that teaches it
        keeps the word counting; a stranger the list never names still goes.

        This was two passes over the finished corpus, each rebuilding every
        sentence it touched. Doing it during the read costs one dictionary
        lookup per unit row and rebuilds nothing.
        """
        if not strict and not list_only:
            return None
        goals = frozenset(self.goal_units)
        aliases = self.aliases
        if list_only and not strict:
            # `of` answers with a goal or with the unit itself, so "is the
            # answer a goal" is exactly "did the list have a name for it".
            return lambda unit: (named if (named := aliases.of(unit)) in goals
                                 else None)
        # A goal is already the name the list teaches by, so it stands as
        # itself; everything else is asked whether the list has a name for it.
        return lambda unit: unit if unit in goals else aliases.of(unit)

    def apply_overrides(self, sentences: list, resolve=None) -> list:
        """What the reader has said about particular sentences, applied.

        Public because the reading page needs it too: a deck stored with a
        roadmap step predates every correction made since, and the two buttons
        under each slide have to reach it somehow. Both are a query against
        the overrides rather than anything to do with a corpus, so they can be
        applied to stored sentences on the way out.
        """
        hidden = self.overrides.hidden()
        corrected = self.overrides.corrected()
        # A removed channel is applied here too, and for the same reason: a
        # stored deck predates the decision as much as it predates a hidden
        # sentence, and every live load passes this way as well.
        banned = self.banned_videos()
        if not hidden and not corrected and not banned:
            return sentences
        out = []
        for sentence in sentences:
            if sentence.text in hidden:
                continue
            if banned and sentence.timing \
                    and sentence.timing.video_id in banned:
                continue
            fix = corrected.get(sentence.text)
            if fix is not None:
                # A correction replaces the units outright, and those units
                # have not been past `resolve` — the store applied it to what
                # it read, and this did not come from the store. Resolving
                # here keeps a corrected sentence counted the same way as
                # every other one.
                items = []
                for unit, surface in fix.items():
                    stands = unit if resolve is None else resolve(unit)
                    if stands is not None:
                        items.append((stands, surface))
                sentence = sentence.with_units(
                    frozenset(unit for unit, _ in items),
                    tuple((unit, surface) for unit, surface in items if surface),
                )
            out.append(sentence)
        return out

    def example_index(self, *builds: str) -> ExampleIndex:
        return ExampleIndex(self.corpus(*builds))

    def prompts(self, *builds: str) -> PromptBuilder:
        return PromptBuilder(
            self.example_index(*builds), self.settings.examples_per_card,
            translate=self.with_english,
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
        units = ({Unit.exact(lemma) for lemma in self._known_lemmas()}
                 # `exact`, so `das Leben` reaches the noun `Leben` and not
                 # only the verb `leben` the database resolves it to.
                 | self.marked_known.units())
        # Under the list's own names as well as the reader's. Vocabulary
        # files give bare lemmas, and strict counting renames those to the
        # goal that teaches them — so a reader who knows `schule` has to be
        # credited with `die Schule` or every sentence saying it grows an
        # unknown that was never there. Added rather than substituted,
        # because the non-strict corpora still say the bare form.
        units |= {self.aliases.of(unit) for unit in units}
        # And the compounds those words already cover. Closed here rather
        # than only inside the walk so that every reader of this agrees with
        # it: the rail beside a sentence, the "needs N more words" counts,
        # the video ranking. Closed in the walk as well, because that learns
        # as it goes and completes compounds the seed could not.
        return KnownSet(units | self.compounds.derivable(units))

    def verdicts(self) -> dict[str, float]:
        """What anyone has said about particular sentences, for ranking.

        Read fresh rather than cached: a reader marking a sentence bad
        expects the next page to stop offering it, and this is one small
        query against a table that holds only what has been judged.
        """
        return self.overrides.verdicts()

    def beginner_set(self) -> KnownSet:
        """What someone opening this for the first time knows.

        The function words and nothing else. `known_set` also carries
        `known_words.txt` and everything this reader has marked while
        reading, which is one person's vocabulary rather than a new one's — a
        plan built on it is a plan for them.

        Filtered out of the full set rather than resolved separately, so both
        go through the same lemmatisation and the two are comparable: 86
        units against 131, which costs exactly one goal of 4,002 (`belieben`)
        and makes the plan longer, because more has to be taught.
        """
        from vocab.loader import WordListLoader          # noqa: PLC0415

        surfaces = set(WordListLoader().load(
            self.settings.function_words).surfaces)
        units = {unit for unit in self.known_set().units
                 if unit.key in surfaces or unit.key.lower() in surfaces}
        units |= {self.aliases.of(unit) for unit in units}
        return KnownSet(units | self.compounds.derivable(units))

    @cached_property
    def compounds(self) -> Compounds:
        """Compound words resolved against this corpus's own lemmas.

        Cached because the resolution needs the corpus's lemma inventory, and
        the vocabulary is re-resolved on every request.
        """
        inventory = {Unit.exact(key) for key in self.corpus_store.lemma_keys()}
        inventory |= {Unit.exact(lemma) for lemma in self._known_lemmas()}
        # `covered_by` as well as the corpus, because strict counting
        # renames the bare `haus` in every sentence to the goal `das Haus`
        # that teaches it. See `Compounds`.
        return Compounds.over(inventory, covered_by=self.covered_by)

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
        with Database(self.settings.own) as db:
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
        stored = self.settings.goal_entries
        files = [self.settings.goal_words, self.settings.goal_lemmas]
        if stored is None:
            cached = self.resolved.get("goals", files)
            if cached is not None:
                return tuple(Unit(kind, key) for kind, key in cached)
        with Database(self.settings.own) as db:
            patterns = PatternRepository(db, self.settings.language).canonicals()
        units = GoalList(self.settings.goal_words, stored).units(
            patterns, self.analyzer.lemmatise_each,
            GoalList.corrections(self.settings.goal_lemmas),
        )
        if stored is None:
            self.resolved.put("goals", files, [[u.kind, u.key] for u in units])
        else:
            # Nothing to stamp a cache with: the entries came from a table
            # the file-mtime cache cannot see, and a stale answer here is a
            # roadmap aimed at the list as it used to be. Two seconds a run,
            # against silently teaching the wrong thing.
            pass
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
