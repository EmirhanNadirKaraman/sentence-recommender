"""What each page shows.

The reading page is served from the stored roadmap when there is one whose
stamp still holds: the step, the deck of sentences that teach it, and the
video each came from were all decided during the walk, and reading them back
costs a query instead of a corpus.

Everything that depends on what the reader knows *now* is still worked out
now — what else in a sentence is new, which words are already marked. Only
the choice of which sentences to offer is settled in advance.

Without a usable stored plan the page falls back to walking a live index,
which is the same answer computed the slow way. Every other page still works
that way.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
from html import escape
from queue import Queue
from threading import Lock, Thread
from urllib.parse import quote

from config import Settings
from fingerprint import analyser_fingerprint
from scores import ScoreStore
from watchability import ENOUGH_LINES, watchability

# Bump when scoring changes: the stored rows are only valid for
# the code that wrote them.
SCORE_VERSION = 4

# How many next-best words to keep per video. The panel shows eight;
# storing more would be paying to remember what nobody reads.
NEXT_WORDS = 8
from corpus.sentence import Sentence
from db import Database
from roadmap import (
    CorpusIndex, ExampleIndex, KnownSet, RoadmapBuilder, UnitPriority,
)
from roadmap.examples import DECK_SIZE
from roadmap.step import RoadmapStep
from roadmap.videos import VideoRoadmapStore
from roadmap.store import ALL, RoadmapStore, current_stamp
from vocab.entry import LEMMA, PATTERN, Unit
from web import watch as video
from web.render import layout, sentence, stamped

PAGE_SIZE = 40

# Ceiling on the exhaustive walk behind the blocked list, so a large corpus
# cannot hang the page.
WALK_LIMIT = 5000
PREFERRED = ("subtitle", "subtitle:llm", ALL)
LABELS = {ALL: "everything", "subtitle": "video subtitles",
          "subtitle:llm": "video subtitles, model-corrected",
}


@dataclass
class Scope:
    """Everything needed to answer "what is i+1" for one corpus."""

    sentences: list[Sentence]
    index: CorpusIndex
    builder: RoadmapBuilder
    examples: ExampleIndex
    priority: UnitPriority


class Viewer:
    def __init__(self, app) -> None:
        self.app = app
        self._known = None
        self._scopes: dict[str, Scope] = {}
        self._store = RoadmapStore(app.settings.state_path)
        self._video_plan = VideoRoadmapStore(app.settings.state_path)
        # Blocked-set results, per source. The walk behind them is cheap on a
        # subtitle corpus and slow on a quarter of a million sentences.
        self._stuck: dict[str, list] = {}
        # Videos grouped, and their metadata. None of it depends on what the
        # reader knows, so it survives marking a word known — the scores are
        # recomputed each load, the grouping is not.
        self._videos: dict[str, dict] = {}
        # Scored rankings, in memory for this request and on disk between
        # runs. `mark_known` drops the memory copy; the stored one is stamped,
        # so it invalidates itself.
        self._ranked: dict[str, list[dict]] = {}
        self._unit_videos: dict[str, dict] = {}
        # One scoring pass at a time; the rest wait and find it done.
        self._scoring = Lock()
        # Marked words waiting to be scored. `_rescore` reaches `_grouped`,
        # which materialises the whole corpus on a cold cache — twenty-three
        # seconds, measured, on the thread answering the POST. Swiping a word
        # away should not wait for that, so it is handed to one worker and
        # answered immediately.
        self._marks: Queue = Queue()
        self._worker: Thread | None = None
        self._scores = ScoreStore(app.settings.state_path)
        self._durations: dict[str, float] | None = None
        self._video_titles: dict[str, str] | None = None
        # The quiz pool: every live line in the vocabulary files, grouped into
        # the units they stand for. Rebuilt when an answer changes the files.
        # Which builds exist and how big they are. Every page asks, through
        # `source()`, and the answer is a GROUP BY over two hundred thousand
        # sentence rows — a fifth of a second, on every request, to decide
        # which corpus was meant. It changes only when a build does.
        self._sources: dict[str, int] | None = None
        self._quiz: dict[str, tuple] = {}
        # What the last denial struck, so it can be put back. The lines cannot
        # be recomputed after the fact — they are commented out, and the pool
        # skips commented lines — so they are kept rather than derived. One
        # entry, because there is one reader and one last answer.
        self._struck: tuple | None = None
        # Words set aside for now. Not written down: a skip is "not this one,
        # not yet", which is a fact about the sitting rather than about the
        # vocabulary, and it should not survive a restart the way an answer
        # does. Kept here because the page asks one question per request and
        # has nowhere else to remember that it already offered this word.
        self._skipped: set[Unit] = set()

    # --- the quiz ---------------------------------------------------------

    def _quiz_pool(self, source: str) -> tuple[dict, Counter, list]:
        """The words still to be checked, most frequent first.

        Ordered rather than sampled. `--sample` on the command line draws a
        set once and bounds what it finds; a page serving one question per
        request would redraw every time, from a pool that shrinks as it goes,
        which is not the same experiment and could not be summarised as one.
        The flag stays where it means something.
        """
        from commands.quiz import QuizCommand   # noqa: PLC0415

        if source not in self._quiz:
            counts = QuizCommand._frequencies(self.app, source)
            grouped: dict[Unit, list[dict]] = {}
            for entry in QuizCommand()._entries(self.app, counts):
                grouped.setdefault(entry["unit"], []).append(entry)
            QuizCommand._merge_frames(grouped)
            self._quiz[source] = (grouped, counts)
        grouped, counts = self._quiz[source]
        checked = self.app.checked.units()
        _, pending = QuizCommand.pool(
            grouped, counts, checked | self._skipped, limit=1, known=self.known)
        # Skipping everything is not finishing. When the pool runs out with
        # words still set aside, they come back round rather than the page
        # claiming there is nothing left to ask.
        if not pending and self._skipped:
            self._skipped.clear()
            _, pending = QuizCommand.pool(grouped, counts, checked, limit=1,
                                          known=self.known)
        return grouped, counts, pending

    def _question(self, source: str) -> str:
        """One word to judge: what it is, how much it matters, and a sentence.

        The example is what makes this answerable. A word out of context is a
        spelling, and the honest answer to most spellings is "I think so".
        """
        from commands.quiz import QuizCommand   # noqa: PLC0415

        grouped, counts, pending = self._quiz_pool(source)
        # Read once. Asked inside the loop below it was a query per group —
        # eight hundred and eighty-four of them, 1.38s to build one question.
        checked = self.app.checked.units()
        done = len(checked)
        if not pending:
            return ("<p class='empty'>Every assumed-known word has been "
                    "checked. Nothing left to ask.</p>")
        group = pending[0]
        unit = group[0]["unit"]
        written = " / ".join(sorted({e["surface"] for e in group}))
        # Several, because one is a gamble: the best-scoring sentence is the
        # right length and sometimes says nothing that helps you recognise the
        # word. The rest travel with the question so asking for another costs
        # no round trip.
        found = QuizCommand.examples(self.app, unit, source,
                                     self.app.overrides.hidden(), want=5)
        example = found[0] if found else ""
        more = (f" data-more=\"{escape(json.dumps(found[1:]))}\""
                if len(found) > 1 else "")
        another = ("<button type='button' class='another'>another sentence"
                   "</button>" if len(found) > 1 else "")
        left = sum(1 for g in grouped.values()
                   if counts.get(g[0]["unit"], 0) and g[0]["unit"] not in checked)
        aside = (f" · {len(self._skipped):,} set aside"
                 if self._skipped else "")
        return (
            "<div class='deck quizcard'>"
            f"<p class='count'>{done:,} checked · {left:,} to go{aside}</p>"
            f"<h2 class='de'>{escape(written)}</h2>"
            f"<p class='quiet'>said {counts[unit]:,} times in this corpus</p>"
            + (f"<div class='example'{more}>{sentence(example, None)}</div>"
               f"{another}"
               if example else "<p class='quiet'>no example sentence</p>")
            + "<form method='post' action='/quiz' class='actions'>"
            f"<input type='hidden' name='kind' value='{escape(unit.kind)}'>"
            f"<input type='hidden' name='key' value='{escape(unit.key)}'>"
            f"<input type='hidden' name='src' value='{escape(source)}'>"
            "<button name='action' value='no' class='no'>Don't know it</button>"
            "<button name='action' value='skip' class='skip'>Skip</button>"
            "<button name='action' value='know' class='yes'>I know it</button>"
            "</form></div>")

    def quiz(self, query: dict) -> str:
        """Check the words the roadmap assumes you already know.

        The same audit as `python main.py quiz`, asking the same questions
        through the same pool, because it is one decision either way and two
        of them would drift. What the page adds is that it can be done on a
        phone — which is where this gets used, and a terminal is not.
        """
        source = self.source(query)
        return layout("Quiz", self.switch(source, "/quiz") +
                      "<h1>Do you know these?</h1>"
                      "<p class='quiet'>Every word here is one the roadmap "
                      "already counts as known. Swipe right if that is true, "
                      "left if it is not.</p>"
                      "<div class='card' id='quiz-card'>"
                      f"<div id='quiz'>{self._question(source)}</div></div>"
                      # `layout` does not carry the script; every page that
                      # wants behaviour asks for it. Without this the whole
                      # controller was simply absent and the swipes did
                      # nothing, silently, which is exactly how it looked.
                      f"<script src='{stamped('app.js')}'></script>",
                      "/quiz", source)

    def quiz_json(self, query: dict) -> dict:
        """The next question, for answering without a page load."""
        source = self.source(query)
        html = self._question(source)
        return {"html": html, "empty": "actions" not in html}

    def answer_quiz(self, form: dict) -> str:
        """Record one answer.

        A yes is a confirmation and nothing else — the word was already
        assumed known, so what changes is that somebody has now looked at it.
        A no comments the line out of the vocabulary file, which is what both
        files document as the way to say you do not know something, and which
        is a write to a tracked file from a thumb on a phone. Hence undo.
        """
        from commands.quiz import QuizCommand   # noqa: PLC0415

        source = form.get("src", "")
        action = form.get("action", "")
        unit = Unit(form.get("kind", ""), form.get("key", ""))
        back = f"/quiz?src={quote(source)}" if source else "/quiz"
        if action == "undo":
            return self._undo_answer(back)
        if not unit.key:
            return back
        if action == "skip":
            self._skipped.add(unit)
            return back

        if action == "no":
            grouped, _, _ = self._quiz_pool(source)
            group = grouped.get(unit, [])
            by_path: dict = {}
            for entry in group:
                by_path.setdefault(entry["path"], []).append(entry["line"])
            for path, lines in by_path.items():
                QuizCommand._comment_out(path, lines)
            self.app.checked.forget(unit)
            self._struck = (unit, by_path)
            self._quiz.pop(source, None)      # the files changed
        else:
            self.app.checked.confirm(unit)
            self._struck = (unit, None)
        return back

    def _undo_answer(self, back: str) -> str:
        """Put the last answer back, whichever way it went."""
        from commands.quiz import QuizCommand   # noqa: PLC0415

        if not self._struck:
            return back
        unit, by_path = self._struck
        self._struck = None
        if by_path is None:
            self.app.checked.forget(unit)
        else:
            for path, lines in by_path.items():
                QuizCommand.restore(path, lines)
            self._quiz.clear()
        return back

    # --- scope ------------------------------------------------------------

    def sources(self) -> dict[str, int]:
        if self._sources is None:
            known = self.app.corpus_store.builds(teachable_only=True)
            out = {name: count for name, count in known.items()}
            if len(out) > 1:
                out[ALL] = sum(out.values())
            self._sources = out
        return self._sources

    def source(self, query: dict) -> str:
        available = self.sources()
        asked = query.get("src")
        if asked in available:
            return asked
        return next((s for s in PREFERRED if s in available),
                    next(iter(available), ALL))

    @staticmethod
    def _builds(source: str) -> tuple[str, ...]:
        return () if source == ALL else tuple(source.split("+"))

    @property
    def known(self) -> frozenset[Unit]:
        if self._known is None:
            self._known = self.app.known_set()
        return self._known.units

    def counting(self, query: dict) -> bool:
        """Whether to count only what the study list names. Default no.

        It used to default yes, on the grounds that the list is what the
        reader set out to learn. That is still true of what gets *taught* —
        both roadmaps teach the list and nothing else — but it was never a
        good answer to what gets *counted*, because narrowing lets a sentence
        be called readable while holding a word you cannot read. The strict
        roadmap counts every word and is the better default; this is how you
        ask for the older, looser reading back.
        """
        return (query.get("count") or "all") == "list"

    def scope(self, source: str, list_only: bool = True) -> Scope:
        """The live index for one corpus, built once and kept current.

        Keyed by counting mode as well as corpus: narrowing to the study list
        gives genuinely different unknown counts, so the two cannot share.

        `list_only=False` means the *strict* corpus, not the raw one — the
        duplicate forms are still dropped, only genuine strangers are kept.
        The default here still reads True, but `counting()` now defaults to
        strict, so nearly every caller passes False.
        """
        key = f"{source}|{'list' if list_only else 'all'}"
        if key not in self._scopes:
            # Not narrowed means strict, not raw: the bare lemma the
            # analyser yields beside the goal that already teaches it is one
            # word arriving twice, and counting it as unknown is bookkeeping
            # rather than vocabulary. See `Application.covered_forms`.
            sentences = self.app.corpus(*self._builds(source),
                                        list_only=list_only,
                                        strict=not list_only)
            # The resolved vocabulary, not a fresh resolution: known_set()
            # re-runs the parser over every word in the files, which is
            # sixteen seconds, and this viewer already holds the answer.
            index = CorpusIndex(sentences, KnownSet(self.known))
            priority = self.app.priority()
            self._scopes[key] = Scope(
                sentences=sentences,
                index=index,
                # Aimed at the study list, not merely filtered by it: a
                # goal outscores anything that is not one, so Next offers a
                # word you meant to learn whenever one is i+1.
                builder=RoadmapBuilder(index, priority,
                                       self.app.settings.priority_weight,
                                       frozenset(self.app.goal_units)),
                examples=ExampleIndex(sentences),
                priority=priority,
            )
        return self._scopes[key]

    def counting_switch(self, query: dict, page: str) -> str:
        source = self.source(query)
        here = "list" if self.counting(query) else "all"
        links = "".join(
            f"<a href='{page}?src={quote(source)}&count={value}' "
            f"class='{'on' if here == value else ''}'>{label}</a>"
            for value, label in (("all", "every word in the sentence"),
                                 ("list", "only my study list"))
        )
        return f"<div class='switch'><span>Counting</span>{links}</div>"

    def switch(self, source: str, page: str) -> str:
        counts = self.sources()
        if len(counts) < 2:
            return ""
        links = "".join(
            f"<a href='{page}?src={quote(name)}' "
            f"class='{'on' if name == source else ''}'>"
            f"{escape(LABELS.get(name, name))}</a>"
            for name in sorted(counts, key=lambda n: (n != ALL, n))
        )
        return f"<div class='switch'><span>Studying</span>{links}</div>"

    # --- what is next -----------------------------------------------------

    def next_up(self, query: dict) -> str:
        source = self.source(query)
        only = query.get("only") or ""
        switch = self.switch(source, "/") + self.counting_switch(query, "/")
        picker = self._kind_picker(only, source)

        # Both readings have a stored roadmap now, so the switch picks one
        # rather than choosing between a stored answer and a slow live walk.
        planned = self._planned(source, only, self.counting(query))
        if planned is not None:
            step, deck, total = planned
            readable, occurrences = step.readable, step.occurrences
        else:
            step, deck, readable, occurrences, total = self._walked(
                query, source, only)

        if step is None:
            body = (switch + picker + "<h1>Nothing left that is i+1</h1>"
                    "<p class='empty'>Every remaining sentence needs two or more "
                    "new things. Widen the filter, add another corpus, or "
                    "run <code>python main.py review</code>.</p>")
            return layout("i+1", body, "/", source)

        unit = step.unit
        watchable = self._has_video(deck)
        # A pattern step is the confusing case: every word reads fine and only
        # the grammar is new, so say that rather than claiming a hidden word.
        if unit.is_pattern:
            lede = ("You know every word in this sentence. What is new is the "
                    "pattern the verb takes — which cases it needs.")
            kind = "a verb pattern"
        else:
            lede = "Everything in this sentence is yours except one word."
            kind = "a word"
        body = (
            switch + picker
            # Everything from here down is replaced in place when a word is
            # decided, so it is built once and shared with `/api/next`.
            # Three pieces, and the split is forced by the player: it must
            # sit *outside* whatever gets replaced, or a decision tears down
            # the iframe and the YouTube API has to boot again — a second or
            # two of nothing, on the action taken most often.
            + f"<div id='reading-top'>{self._progress(readable, total)}"
            + f"<p class='note'>{lede}</p></div>"
            + self._audio_toggle()
            + "<div class='card' id='card'>"
            + self._stage(deck)
            + "<div id='reading'>"
            + self._reading(step, deck, source, occurrences, kind, watchable)
            + "</div></div>"
            + ("<h2>Transcript</h2><ol class='transcript' id='transcript'></ol>"
               if watchable else "")
            + video.merged_script()
        )
        return layout("i+1", body, "/", source)

    def _reading(self, step, deck, source, occurrences, kind,
                 watchable) -> str:
        """Everything a decision replaces, minus the player above it."""
        unit = step.unit
        return (
            self._deck(deck, unit, source)
            + "<h2>The new thing</h2>"
            f"<p class='de'>{escape(unit.key)}</p>"
            f"<p class='en'>{kind}, appearing in {occurrences:,} sentence"
            f"{'s' if occurrences != 1 else ''} here and opening {step.gain} "
            f"more</p>"
            + self._actions(unit, source, "/", watchable=watchable)
        )

    def next_json(self, query: dict) -> dict:
        """The next word, for swapping in without a page load.

        The reading page reloaded on every decision, which meant tearing down
        the YouTube iframe and building it again — a second or two of nothing,
        on the action taken most often. The reels feed avoids that by keeping
        its player; this does the same.
        """
        source = self.source(query)
        only = query.get("only") or ""
        # No gate here. An earlier version of `next_up` only consulted the
        # stored plan under study-list counting, and copying that condition
        # across sent every request down the live walk instead — 41s a swipe,
        # for the endpoint whose entire purpose was to make swiping instant.
        planned = self._planned(source, only, self.counting(query))
        if planned is not None:
            step, deck, total = planned
            readable, occurrences = step.readable, step.occurrences
        else:
            step, deck, readable, occurrences, total = self._walked(
                query, source, only)
        if step is None:
            return {"empty": True}
        unit = step.unit
        watchable = self._has_video(deck)
        if unit.is_pattern:
            lede = ("You know every word in this sentence. What is new is the "
                    "pattern the verb takes — which cases it needs.")
            kind = "a verb pattern"
        else:
            lede = "Everything in this sentence is yours except one word."
            kind = "a word"
        first = next((x for x in deck if x.timing), None)
        return {
            "top": (self._progress(readable, total)
                    + f"<p class='note'>{lede}</p>"),
            "html": self._reading(step, deck, source, occurrences, kind,
                                  watchable),
            "video": first.timing.video_id if first else "",
            "at": first.timing.start if first else 0,
        }

    def _planned(self, source: str, only: str, list_only: bool
                 ) -> tuple[RoadmapStep, list[Sentence], int] | None:
        """The next step of the stored plan the reader has not taken, and its
        deck.

        This is the whole reason the page opens without a corpus: the walk
        already decided which sentences teach this step, against what a reader
        following the plan knows by the time they reach it. Reading them back
        is one query.

        What it costs is that the deck was chosen then and not now. A reader
        who has marked words in a different order than the plan gets sentences
        ranked for a slightly different vocabulary than their own — still
        sentences that teach the step, just not necessarily the most readable
        ones they could have been offered. What else is new in each is still
        counted against what they know at this moment, so nothing on the page
        claims to be i+1 when it is not.

        None when there is nothing worth serving: no stored roadmap for this
        corpus, one built before the decks existed, or one whose stamp no
        longer matches the rules in force. The caller falls back to walking a
        live index, which is the same answer computed the slow way.
        """
        label = self._stored_label(source, list_only)
        if self._store.stamp(label) != current_stamp():
            return None
        known = self.known
        steps = self._store.load(label)

        def first(skip: frozenset[Unit]):
            # Patterns are grammar, not vocabulary. Some days you want one and
            # not the other, so they can be stepped over without being learned.
            return next((s for s in steps
                         if s.unit not in known and s.unit not in skip
                         and not (only == "word" and s.unit.is_pattern)), None)

        # Twice, if the first pass finds nothing. Everything left being set
        # aside is not the same as nothing being left, and "nothing is i+1"
        # would be a lie when the only thing in the way is your own skips.
        # Better to offer a word early than to claim the corpus is exhausted.
        step = first(self.app.snoozes.asleep()) or first(frozenset())
        if step is not None:
            deck = self._store.deck(label, step)
            # A step with nothing written against it is a step from before the
            # decks existed. Falling back beats an empty page.
            if not deck:
                return None
            # Everything the reader has said about these sentences since the
            # roadmap was built. Without this, "drop this sentence" and "fix
            # its words" — rendered under every slide — would do nothing here
            # until the next rebuild.
            deck = self.app.apply_overrides(deck)
            return (step, deck, self._store.total(label)) if deck else None
        return None

    def _walked(self, query: dict, source: str, only: str
                ) -> tuple[RoadmapStep | None, list[Sentence], int, int, int]:
        """The same answer, computed from a live index over the corpus.

        The original behaviour, and still the honest one: it recomputes what
        is i+1 against everything marked known this instant. It is kept as the
        fallback, and it is what runs whenever the stored plan cannot be
        trusted.
        """
        scope = self.scope(source, self.counting(query))
        skip = set(self.app.snoozes.asleep())
        if only == "word":
            skip |= {u for u in scope.index.known_units_of_kind(PATTERN)}
        step = scope.builder.peek(
            exclude=frozenset(skip),
            kinds=frozenset({LEMMA}) if only == "word" else frozenset(),
        )
        if step is None:
            return None, [], scope.index.readable, 0, len(scope.sentences)
        return (step,
                scope.examples.examples(step.unit, self.known, limit=DECK_SIZE),
                scope.index.readable,
                scope.examples.count(step.unit),
                len(scope.sentences))

    @staticmethod
    def _audio_toggle() -> str:
        """Hide the picture and keep the sound.

        Rendered on every page that has a player. The state lives in the
        browser rather than the URL or the database: it is a property of how
        you are using the phone this minute — pocket or hand — not of what
        you are learning.
        """
        return ("<button type='button' class='mode' id='mode'>"
                "listening, not watching</button>")

    @staticmethod
    def _progress(readable: int, total: int) -> str:
        """How far along the reader is, against what.

        The denominator is not decoration. This page counts over whatever the
        roadmap was walked over, and `--quality` walks 41,394 of 115,461
        sentences — so the same wording over the same corpus honestly produced
        27,971 one day and 5,720 the next. Saying both numbers is the only
        version that cannot be read two ways.

        A roadmap built before the total was recorded says nothing rather than
        guessing at one.
        """
        if not total:
            return f"<h1>{readable:,} sentences you can already read</h1>"
        return (f"<h1>{readable:,} of {total:,} sentences you can already "
                f"read</h1>")

    @staticmethod
    def _stage(deck: list[Sentence]) -> str:
        """The player, opened on the first sentence the deck will show.

        Rendered here rather than behind a link: the point of a subtitle
        corpus is that every sentence was said out loud, so hearing one should
        be the default rather than a second click. Returns nothing when no
        sentence in the deck has a video — a generated one, or one whose
        timing was never recorded.
        """
        first = next((s for s in deck if s.timing), None)
        return video.stage(first.timing.video_id, first.timing.start) if first else ""

    def transcript_json(self, video_id: str) -> dict:
        """Every cue of one video, for the transcript beside the player.

        Fetched per video rather than shipped with the page: the deck can
        touch a dozen videos and their cues together would be most of the
        bytes.
        """
        return {"cues": [
            {"at": round(c.timing.start, 2), "clock": _clock(c.timing.start),
             "text": c.text}
            for c in self._cues(video_id)
        ]}

    def _deck(self, options: list[Sentence], unit: Unit,
              source: str = "") -> str:
        """The sentences using `unit`, readable ones first, stepped in place.

        How far the deck reaches is decided by the walk that filled it, not
        here. On the study-list roadmap it reaches past the strictly-i+1
        sentences into the rest: there are often only one or two of the
        former — `etw. (Akk) können` appears in 131 subtitle sentences and is
        the sole unknown in one — and stopping there would leave nothing to
        step through, so the rest follow, each saying what else in it is new.

        The strict roadmap stops at the i+1 set however short that leaves it,
        because reaching further would offer exactly the sentences it exists
        to exclude — ones holding a word the walk will never teach. Either
        way this method only renders what it was handed.
        """
        known = self.known
        if not options:
            return ""
        slides = "".join(
            f"<div class='slide'{'' if i == 0 else ' hidden'}"
            + (f" data-video='{escape(s.timing.video_id)}' "
               f"data-at='{s.timing.start:.2f}'" if s.timing else "")
            + ">"
            f"{sentence(s.text, s.translation, s.surface_of(unit), lead=True)}"
            f"{self._also_new(s, unit, known)}"
            f"{self._sentence_tools(s.text, source, '/')}</div>"
            for i, s in enumerate(options)
        )
        if len(options) == 1:
            return f"<div class='deck' id='deck'>{slides}</div>"
        readable = sum(1 for s in options if not (s.units - known - {unit}))
        return (
            f"<div class='deck' id='deck'>{slides}</div>"
            "<div class='stepper'>"
            "<button type='button' id='prev' aria-label='Previous sentence'>"
            "&#8592;</button>"
            f"<span class='count'><span id='at'>1</span> of {len(options)}"
            "</span>"
            "<button type='button' id='next' aria-label='Next sentence'>"
            "&#8594;</button>"
            # Naming both axes, because the right arrow is no longer a
            # way of looking around: it marks the word known.
            "<span class='hint'>&uarr;&darr; another sentence &nbsp; "
            "&rarr; know it &nbsp; &larr; later &nbsp;&nbsp; "
            + (f"{readable} of them need only this"
               if readable != 1 else "one of them needs only this")
            + "</span></div>"
        )

    @staticmethod
    def _also_new(sentence_, unit: Unit, known: frozenset[Unit]) -> str:
        """What else in this sentence is unknown — why it is harder than i+1."""
        rest = sorted(u.key for u in sentence_.units - known - {unit})
        if not rest:
            return "<p class='also clear'>Nothing else here is new.</p>"
        shown = ", ".join(escape(k) for k in rest[:4])
        more = f" and {len(rest) - 4} more" if len(rest) > 4 else ""
        return f"<p class='also'>Also new: {shown}{more}</p>"

    @staticmethod
    def _sentence_tools(text: str, source: str, back: str) -> str:
        """Per-sentence corrections, for when the analyser got it wrong.

        Kept small and quiet: these are for the exception, not the reading.
        """
        fields = (f"<input type='hidden' name='text' value='{escape(text)}'>"
                  f"<input type='hidden' name='src' value='{escape(source)}'>"
                  f"<input type='hidden' name='back' value='{escape(back)}'>")
        return (
            "<div class='tools'>"
            f"<form method='post' action='/hide'>{fields}"
            "<button name='action' value='hide'>Drop this sentence</button>"
            "</form>"
            f"<a class='link' href='/fix?text={quote(text, safe='')}"
            f"&src={quote(source)}&back={quote(back, safe='')}'>Fix its words</a>"
            "</div>"
        )

    def fix(self, query: dict) -> str:
        """A sentence's units, as a list you can correct.

        The analyser decides these from a parse; when it decides wrongly there
        is no threshold that helps, only saying what the sentence actually
        contains.
        """
        source = self.source(query)
        text = query.get("text", "")
        back = query.get("back") or "/"
        # Always the unfiltered analysis, whatever the counting switch says:
        # this page exists to correct what the analyser found, and the units
        # most worth removing are the ones the study list would have hidden.
        # One sentence, asked for by name. It used to be found by walking
        # every sentence of the corpus in memory.
        holding = self.app.corpus(*self._builds(source), strict=True, text=text)
        found = holding[0] if holding else None
        if found is None:
            return layout("Fix", "<h1>No such sentence</h1><p class='empty'>It "
                          "may have been dropped already.</p>", "/roadmap", source)

        known = self.known
        boxes = "".join(
            "<label class='box'>"
            f"<input type='checkbox' name='unit' value='{escape(u.kind)}|{escape(u.key)}'"
            " checked>"
            f"<span class='de'>{escape(u.key)}</span>"
            f"<span class='quiet'>{'pattern' if u.is_pattern else 'word'}"
            f"{' · known' if u in known else ''}</span></label>"
            for u in sorted(found.units, key=lambda x: (x.kind, x.key))
        ) or "<p class='empty'>The analyser found nothing in this sentence.</p>"

        body = (
            "<h1>What is in this sentence?</h1>"
            f"<p class='de lead'>{escape(text)}</p>"
            "<p class='note'>Uncheck anything that is not really here, and add "
            "what is missing. Corrections are kept by sentence text, so "
            "rebuilding the corpus does not lose them.</p>"
            f"<form method='post' action='/fix'>"
            f"<input type='hidden' name='text' value='{escape(text)}'>"
            f"<input type='hidden' name='src' value='{escape(source)}'>"
            f"<input type='hidden' name='back' value='{escape(back)}'>"
            f"<div class='boxes'>{boxes}</div>"
            "<div class='bar'>"
            "<input type='text' name='add' autocomplete='off' "
            "placeholder='words to add, separated by commas'>"
            "<button class='go' name='action' value='save'>Save</button>"
            "<button name='action' value='reset'>Use the analyser's answer"
            "</button></div></form>"
        )
        return layout("Fix", body, "/roadmap", source)

    def save_fix(self, form: dict) -> str:
        """Store a correction, or throw one away, and go back to the reading."""
        text = form.get("text", "")
        back = form.get("back") or "/"
        source = form.get("src", "")
        target = f"{back}{'&' if '?' in back else '?'}src={quote(source)}"
        if not text:
            return target

        if form.get("action") == "reset":
            self.app.overrides.clear_units(text)
        else:
            kept: dict[Unit, str] = {}
            for raw in form.get("unit", "").split("\x00"):
                if "|" in raw:
                    kind, key = raw.split("|", 1)
                    kept[Unit(kind, key)] = ""
            for word in form.get("add", "").split(","):
                word = word.strip()
                if word:
                    # Added by hand, so a word — a pattern is not something
                    # anyone types from memory.
                    kept[Unit.lemma(word)] = word
            self.app.overrides.set_units(text, kept)
        self._scopes.clear()          # the corpus in memory is now out of date
        self._stuck.clear()
        return target

    def hide_sentence(self, form: dict) -> str:
        text = form.get("text", "")
        back = form.get("back") or "/"
        source = form.get("src", "")
        if text:
            self.app.overrides.hide(text)
            self._scopes.clear()
            self._stuck.clear()
        return f"{back}{'&' if '?' in back else '?'}src={quote(source)}"

    @staticmethod
    def _kind_picker(only: str, source: str) -> str:
        choices = (("", "words and patterns"), ("word", "words only"))
        links = "".join(
            f"<a href='/?src={quote(source)}"
            + (f"&only={value}" if value else "")
            + f"' class='{'on' if only == value else ''}'>{label}</a>"
            for value, label in choices
        )
        return f"<div class='switch'><span>Teaching me</span>{links}</div>"

    @staticmethod
    def _here(path: str, query: dict, *keys: str) -> str:
        """This page's own address, for a form that has to come back to it.

        Only the keys named travel, because `mark_known` appends `src`
        itself and two of those make a URL that carries neither.
        """
        carried = [(k, query[k]) for k in keys if query.get(k)]
        return path + ("?" + "&".join(f"{k}={quote(str(v), safe='')}"
                                      for k, v in carried) if carried else "")

    @staticmethod
    def _blocker_actions(rest: list, gap: int, source: str, back: str) -> str:
        """Offer to mark the word that is actually in the way.

        The button beside a stranded goal marks the goal known, which is the
        one thing that takes it off the list — but it is not what stands
        between you and the sentence. `palästinensisch` is blocked by
        `geiselnehmer`, a word that is not on the study list at all and that
        the walk will therefore never teach, so no amount of reading frees it.
        Knowing the blocker does.

        Only when there is exactly one, and only when it is named. Of 254
        stranded goals 42 are a single word away, and each of those words
        unlocks exactly one goal — there is no stranger blocking a batch, so
        this is a one-for-one trade and pretending otherwise would oversell
        it. Past one blocker the offer is meaningless: knowing one of three
        leaves the sentence just as unreachable.
        """
        if gap != 2 or len(rest) != 1:
            return ""
        blocker = rest[0]
        return ("<form method='post' action='/known'>"
                f"<input type='hidden' name='kind' value='{escape(blocker.kind)}'>"
                f"<input type='hidden' name='key' value='{escape(blocker.key)}'>"
                f"<input type='hidden' name='src' value='{escape(source)}'>"
                f"<input type='hidden' name='back' value='{escape(back)}'>"
                "<button name='action' value='known'>I know "
                f"{escape(blocker.key)}</button></form>")

    def _word_actions(self, unit: Unit, source: str, back: str,
                      pass_too: bool = True, extra: str = "") -> str:
        """Mark a word without leaving the list it is in.

        The reading page gets the full bar — watch it, read other sentences,
        set it aside. A list wants the one thing you actually do while
        reading down it, and to put you back where you were afterwards, so
        `back` carries the page and the filters rather than a bare path.
        """
        hidden = (f"<input type='hidden' name='kind' value='{escape(unit.kind)}'>"
                  f"<input type='hidden' name='key' value='{escape(unit.key)}'>"
                  f"<input type='hidden' name='src' value='{escape(source)}'>"
                  f"<input type='hidden' name='back' value='{escape(back)}'>")
        passing = (f"<form method='post' action='/known'>{hidden}"
                   "<button name='action' value='pass'>Not yet</button></form>"
                   if pass_too else "")
        return ("<div class='tools'>"
                f"<form method='post' action='/known'>{hidden}"
                "<button name='action' value='known'>I know this</button>"
                f"</form>{passing}{extra}</div>")

    def _actions(self, unit: Unit, source: str, back: str,
                 watchable: bool = False) -> str:
        """What to do about the thing just shown."""
        args = (f"src={quote(source)}&kind={quote(unit.kind)}"
                f"&key={quote(unit.key, safe='')}")
        hidden = (f"<input type='hidden' name='kind' value='{escape(unit.kind)}'>"
                  f"<input type='hidden' name='key' value='{escape(unit.key)}'>"
                  f"<input type='hidden' name='src' value='{escape(source)}'>"
                  f"<input type='hidden' name='back' value='{escape(back)}'>")
        watch = (f"<a class='link' href='/watch?{args}'>Watch it said</a>"
                 if watchable else "")
        return (
            "<div class='actions'>"
            f"<form method='post' action='/known'>{hidden}"
            "<button class='go' name='action' value='known'>I know this</button>"
            "</form>"
            f"{watch}"
            f"<a class='link' href='/unit/{unit.kind}/{quote(unit.key, safe='')}"
            f"?src={quote(source)}'>Other sentences</a>"
            f"<form method='post' action='/known'>{hidden}"
            "<button name='action' value='pass'>Not yet</button></form>"
            "</div>"
        )

    @staticmethod
    def _has_video(deck: list[Sentence]) -> bool:
        """Whether the player and the transcript have anything to show.

        Asked of the deck rather than of the corpus, so the answer matches
        what is actually on the page: a "Watch it said" link beside sentences
        that were never aligned to a video is an offer the page cannot keep.
        """
        return any(s.timing for s in deck)

    # --- marking ----------------------------------------------------------

    def mark_known(self, form: dict) -> str:
        """Record a unit as known, or set it aside, and say where to go next.

        Marking known updates every live index in place, so the next page is
        computed against it immediately rather than waiting for a rebuild.
        """
        unit = Unit(form.get("kind", ""), form.get("key", ""))
        back = form.get("back") or "/"
        source = form.get("src", "")
        if not unit.key:
            return back

        if form.get("action") == "undo":
            self._unmark(unit)
        elif form.get("action") == "pass":
            self.app.snoozes.snooze(unit, self.app.settings.snooze_words)
        else:
            self.app.marked_known.add(unit)
            self.app.card_store.remove(unit)
            # The blocked page is computed against what you know and cached
            # per source, and nothing here was clearing it — so a word you had
            # just learned went on being listed as stranded until the server
            # restarted. Cleared here and not in the `pass` branch, because
            # `_stranded` reads the known set and never the snoozed one.
            self._stuck.clear()
            # Off the shelf rather than left to expire: learning a word should
            # not leave it remembering that it was once avoided.
            self.app.snoozes.wake(unit)
            # Learning is a decision too, and the delay counts decisions —
            # otherwise a session spent marking words known would never bring
            # anything back.
            self.app.snoozes.advance()
            if self._known is not None and unit not in self._known:
                self._known.learn(unit)
            for scope in self._scopes.values():
                if unit not in scope.index.known:
                    scope.index.learn(unit)
            # Last, and the order is the whole point: `_rescore` reads the
            # known set, and reading it before `learn` scored every video
            # against a vocabulary that did not yet contain the word just
            # marked. It did the work and wrote back the numbers it started
            # with.
            self._queue_rescore(unit)
        # `&` when the caller already carried its own state — a list you
        # were forty entries into should come back to entry forty, not to the
        # top. Joining with `?` unconditionally made a second query string and
        # the page silently forgot its page number and filters.
        if not source:
            return back
        return f"{back}{'&' if '?' in back else '?'}src={quote(source)}"

    # --- the rest ---------------------------------------------------------

    def roadmap(self, query: dict) -> str:
        source = self.source(query)
        label = self._stored_label(source, self.counting(query))
        steps = self._store.load(label)
        needle = (query.get("q") or "").strip().lower()
        kind = query.get("kind") or ""
        if needle:
            steps = [s for s in steps if needle in s.unit.key.lower()
                     or needle in s.sentence.text.lower()]
        if kind in ("word", "pattern"):
            steps = [s for s in steps if s.unit.is_pattern == (kind == "pattern")]
        known = self.known
        hidden = 0
        if query.get("hide") == "known":
            before = len(steps)
            steps = [s for s in steps if s.unit not in known]
            hidden = before - len(steps)

        # Carries the filters and the page, so marking a word halfway down
        # comes back halfway down rather than at the top.
        back = self._here("/roadmap", query, "q", "kind", "hide", "page",
                          "count")
        page = max(int(query.get("page") or 1), 1)
        pages = max((len(steps) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        window = steps[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

        entries = "".join(
            "<div class='entry'>"
            f"<div class='rail'>{s.position}<span class='kind'>"
            f"{'known' if s.unit in known else ('pattern' if s.unit.is_pattern else 'word')}"
            "</span></div><div class='body'>"
            f"<div class='unit'><a href='/unit/{s.unit.kind}/"
            f"{quote(s.unit.key, safe='')}?src={quote(source)}'>"
            f"{escape(s.unit.key)}</a></div>"
            f"{sentence(s.sentence.text, s.sentence.translation, s.sentence.surface_of(s.unit))}"
            + ("" if s.unit in known
               else self._word_actions(s.unit, source, back))
            + "</div></div>"
            for s in window
        )
        listing = (f"<div class='ledger'>{entries}</div>" if window
                   else "<p class='empty'>Nothing here matches that.</p>")
        body = (self.switch(source, "/roadmap")
                + self.counting_switch(query, "/roadmap")
                + "<h1>Roadmap</h1>"
                f"<p class='note'>{len(steps):,} steps in the order they were "
                f"planned, saved by the last build of <code>{escape(label)}</code>. The marked word was the only "
                "unknown one in its sentence at that point — anything you have "
                "learned since is labelled <em>known</em> in the rail.</p>"
                f"{self._filters(needle, kind, source, query.get('hide', ''))}"
                f"{self._hidden_note(hidden)}{listing}"
                f"{self._pager(page, pages, needle, kind, source, query.get('hide', ''))}")
        return layout("Roadmap", body, "/roadmap", source)

    def _stored_label(self, source: str, list_only: bool) -> str:
        """The stored roadmap the switches are asking for.

        A roadmap's name carries the settings that built it, so the switches
        name one directly: `subtitle` counting every word is
        `subtitle:strict:goals`, counting only the study list is
        `subtitle:list:goals`. Both teach the list and nothing else — that is
        what `:goals` means, and it is not what the switch chooses. What it
        chooses is which words have to be known before a sentence counts as
        readable.

        Both are built and stored, so either is a query rather than a walk.
        Whichever was asked for wins and the other is the fallback, so a
        corpus with only one of them built still works.

        The well-formed plan wins over the plain one where it exists: it
        teaches from sentences worth reading, at the price of the words this
        corpus only ever says badly. Falling back rather than requiring it,
        so the page works before `build-roadmap --quality` has ever been run.
        """
        stored = self._store.sources()
        # A plan aimed at a list other than the default carries its name, so
        # the page has to ask for it by that name or never find it. Served
        # from whichever list this process was started with, which is what
        # `--goals-file` already means everywhere else.
        named = self.app.settings.goal_words.stem
        tail = "" if named == Settings().goal_words.stem else f":{named}"
        strict = (f"{source}:good:strict:goals{tail}",
                  f"{source}:strict:goals{tail}")
        listed = (f"{source}:good:list:goals{tail}",
                  f"{source}:list:goals{tail}")
        for wanted in (listed + strict) if list_only else (strict + listed):
            if wanted in stored:
                return wanted
        return source

    @staticmethod
    def _hidden_note(hidden: int) -> str:
        if not hidden:
            return ""
        return (f"<p class='note'>{hidden:,} step"
                f"{'s' if hidden != 1 else ''} you have since learned "
                "are hidden.</p>")

    def blocked(self, query: dict) -> str:
        """What the roadmap cannot reach, and what to go looking for.

        Once no sentence has exactly one unknown left the walk halts, and
        everything still unknown is stranded — not because it is hard, but
        because this corpus never says it plainly enough. Ranked by how often
        each appears, because that is what makes finding material for it worth
        the trouble.
        """
        source = self.source(query)
        stranded = self._stranded(source, self.counting(query))
        near_only = query.get("gap") == "near"
        rows = [r for r in stranded if not near_only or r[2] == 2]

        entries = "".join(
            "<div class='entry'>"
            f"<div class='rail'>{count}&times;"
            f"<span class='kind'>{'pattern' if unit.is_pattern else 'word'}</span>"
            "</div><div class='body'>"
            f"<div class='unit'>{escape(unit.key)}</div>"
            + (f"<p class='de'>{escape(example)}</p>"
               # `gap` counts this word too; `rest` does not. Printing the one
               # beside the other read as "2 new things: geiselnehmer", a
               # count of two above a list of one, and the obvious reading —
               # that the single word named was somehow two things — is wrong.
               # Say how many *others* there are, which is what the list holds.
               f"<p class='also'>needs {gap - 1} other new "
               f"word{'' if gap == 2 else 's'} here: "
               f"{escape(', '.join(b.key for b in rest))}"
               f"{f' and {gap - 1 - len(rest)} more' if gap - 1 > len(rest) else ''}"
               "</p>" if example else
               "<p class='also'>Never said in this corpus. Find a clip of it "
               "and the chain continues.</p>")
            # No "not yet" here: nothing on this page is being offered, so
            # there is nothing to defer. Knowing it already is the one thing
            # that takes it off the list.
            + self._word_actions(
                unit, source, self._here("/blocked", query, "gap", "count"),
                pass_too=False,
                extra=self._blocker_actions(
                    rest, gap, source,
                    self._here("/blocked", query, "gap", "count"))
                + "<a class='link' target='_blank' rel='noreferrer' "
                  "href='https://de.youglish.com/pronounce/"
                  f"{quote(_hunt_term(unit), safe='')}"
                  "/german'>Find it on YouGlish</a>")
            + "</div></div>"
            for unit, count, gap, example, rest in rows[:PAGE_SIZE]
        )
        near = sum(1 for r in stranded if r[2] == 2)
        picker = "".join(
            f"<a href='/blocked?src={quote(source)}"
            + (f"&gap={v}" if v else "")
            + f"' class='{'on' if (query.get('gap') or '') == v else ''}'>{label}</a>"
            for v, label in (("", f"all {len(stranded):,}"),
                             ("near", f"one word away ({near:,})"))
        )
        body = (
            self.switch(source, "/blocked")
            + self.counting_switch(query, "/blocked")
            + f"<div class='switch'><span>Showing</span>{picker}</div>"
            "<h1>Where the roadmap stops</h1>"
            f"<p class='note'>{len(stranded):,} words on your study list this "
            "corpus cannot teach, because none of them is ever the only new "
            "thing in a sentence. Every sentence saying one says something "
            "else you do not know as well — often a word that is not on your "
            "list at all, which the walk will therefore never teach, so no "
            f"amount of progress will free it. {near:,} are a single word "
            "away — learn that word, or find a clip that says this one "
            "plainly, and the chain continues.</p>"
            + (f"<div class='ledger'>{entries}</div>" if entries
               else "<p class='empty'>Nothing is stranded — the roadmap "
                    "reaches everything in this corpus.</p>")
            + (f"<p class='note'>Showing the {PAGE_SIZE} most frequent of "
               f"{len(rows):,}.</p>" if len(rows) > PAGE_SIZE else "")
        )
        return layout("Blocked", body, "/blocked", source)

    def _stranded(self, source: str, list_only: bool = True):
        """Goals left unknown once the walk runs out, most frequent first.

        Goals, not units: the walk takes only goals, so what it cannot reach
        is a question about the study list and nothing else. Narrowed
        counting used to give that for free by discarding every non-goal
        before the index was built; counting every word keeps them, so the
        filter has to be said out loud — and a walk left to itself spent two
        minutes learning `Klausur` before reporting it as reachable.

        Computed on a throwaway index: running the walk to exhaustion learns
        everything reachable, and doing that to the live one would tell the
        reading page they know words they have never seen.
        """
        key = f"{source}|{'list' if list_only else 'all'}"
        if key in self._stuck:
            return self._stuck[key]
        scope = self.scope(source, list_only)
        # Reuse the resolved vocabulary rather than asking for it again —
        # known_set() re-runs the parser over every word in the files, which
        # is seconds, and this page already has the answer.
        spare = CorpusIndex(scope.sentences, KnownSet(self.known))
        # Replay the stored plan instead of deriving it again. Learning a unit
        # is a dictionary update; *choosing* one scores every candidate on the
        # frontier, and there are thousands of those. The walk below then only
        # has to cover what the stored plan did not — which, since roadmaps are
        # built to exhaustion, is usually nothing.
        for step in self._store.load(self._stored_label(source, list_only)):
            spare.learn(step.unit)
        # Only goals, because only goals are ever taught — the question is
        # what the roadmap cannot reach, and the roadmap does not reach for
        # anything else. Narrowed counting got this for free, having thrown
        # every non-goal away before the index was built; counting every word
        # keeps them, so a walk left to its own devices spends its time
        # learning `Klausur` and then reports it as reachable. Saying so cost
        # two minutes a page load as well as being wrong.
        goals = frozenset(self.app.goal_units)
        RoadmapBuilder(spare, scope.priority,
                       self.app.settings.priority_weight,
                       goals=goals, only_goals=True).build(max_steps=WALK_LIMIT)
        reached = spare.known

        appearances: Counter = Counter()
        easiest: dict = {}
        for s in scope.sentences:
            unknown = s.units - reached
            if not unknown:
                continue
            # The gap counts every unknown word, including the ones off the
            # list: they are why the sentence cannot teach anything, so they
            # belong in "three new things in its easiest sentence". Only the
            # goals get a row of their own.
            for u in unknown & goals:
                appearances[u] += 1
                if u not in easiest or len(unknown) < easiest[u][0]:
                    # Units rather than keys. The page offers to mark a
                    # blocker known, and `/known` is addressed by kind and
                    # key together — a bare string cannot say whether a word
                    # is the lemma or the pattern.
                    easiest[u] = (len(unknown), s.text,
                                  sorted(unknown - {u}, key=lambda x: x.key)[:4])
        rows = [(u, n, *easiest[u]) for u, n in appearances.most_common()]

        # Goals this corpus never says at all. Far more numerous than the
        # ones it says but cannot isolate, and the actual work — so they
        # belong on the page you mine from, not only in the hunt.
        #
        # Nothing is filtered out. This page answers one question: which words
        # on the study list can these videos not teach me. A goal the analyser
        # would never emit even if it were said belongs in that answer too —
        # hiding it made the list shorter without making it truer.
        priority = scope.priority
        rows += [
            (unit, 0, 0, "", [])
            for unit in sorted(
                (u for u in goals
                 if u not in reached and u not in appearances),
                key=lambda u: -priority.of(u),
            )
        ]
        self._stuck[key] = rows
        return rows

    def unit(self, kind: str, key: str, query: dict) -> str:
        source = self.source(query)
        target = Unit(kind, key)
        known = self.known
        # Asked of the database, not of a corpus in memory. This page wants
        # twenty-five sentences saying one word and used to load all 115,000
        # to find them: forty-six seconds, the slowest thing in the app.
        list_only = self.counting(query)
        holding = self.app.corpus(*self._builds(source), list_only=list_only,
                                  strict=not list_only, holding=(kind, key))
        found = ExampleIndex(holding).examples(target, known, limit=25)

        entries = "".join(
            "<div class='entry'>"
            f"<div class='rail'>{len(s.units - known - {target})}"
            "<span class='kind'>unknown</span></div>"
            f"<div class='body'>{sentence(s.text, s.translation, s.surface_of(target))}"
            + (f"<div class='actions'><a class='link' href='/watch?src={quote(source)}"
               f"&kind={quote(kind)}&key={quote(key, safe='')}&i={i}'>"
               f"Watch at {_clock(s.timing.start)}</a></div>" if s.timing else "")
            + self._sentence_tools(
                s.text, source, f"/unit/{kind}/{quote(key, safe='')}")
            + "</div></div>"
            for i, s in enumerate(found)
        )
        listing = (f"<div class='ledger'>{entries}</div>" if found
                   else "<p class='empty'>No sentence in this corpus uses it. "
                        "Generate one with <code>python main.py fill-gaps</code>.</p>")
        already = target in known
        body = (
            f"<h1>{escape(key)}</h1>"
            f"<p class='note'>{len(holding):,} sentences here use "
            "it. The rail counts what else is unknown in each, so the top ones "
            "are the readable ones.</p>"
            + ("<p class='note'>You have marked this known.</p>" if already
               else self._actions(target, source,
                                  f"/unit/{kind}/{quote(key, safe='')}",
                                  watchable=any(s.timing for s in found)))
            + listing
        )
        return layout(key, body, "/roadmap", source)

    # --- reels ------------------------------------------------------------

    def reels(self, query: dict) -> str:
        """One video at a time, ranked for watching rather than studying.

        The ranking still moves as you learn — that is the whole point of the
        page — but it is no longer recomputed per load to achieve it. Scores
        are read from `video_score` while the stamp holds, and `mark_known`
        updates only the videos that say the word it was given. A warm load
        is a dictionary lookup.

        This said the opposite for a while after it stopped being true, and
        an agent reading it concluded the page needed rearchitecting to avoid
        a corpus scan that had already been removed. Prose about cost earns
        its place only while someone keeps it honest.
        """
        source = self.source(query)
        ranked = self._watchable(source)
        if not ranked:
            return layout("Reels", "<h1>Nothing to watch</h1><p class='empty'>"
                          "No video in this corpus has enough subtitle lines.</p>",
                          "/reels", source)

        here = min(max(int(query.get("i") or 0), 0), len(ranked) - 1)
        row = ranked[here]
        args = f"?src={quote(source)}"
        prev = (f"<a class='link' href='/reels{args}&i={here - 1}'>&larr; easier</a>"
                if here else "<span class='link off'>&larr; easier</span>")
        nxt = (f"<a class='link' href='/reels{args}&i={here + 1}'>harder &rarr;</a>"
               if here + 1 < len(ranked) else "<span class='link off'>harder &rarr;</span>")

        state = json.dumps({"at": here, "total": len(ranked),
                            "src": source, "video": row["video"]})
        body = (
            self.switch(source, "/reels")
            + f"<h1 id='reel-title'>{escape(row['title'] or row['video'])}</h1>"
            + "<p class='note'><span id='reel-at'>" + f"{here + 1}"
            + f"</span> of {len(ranked):,}, ranked by how well it plays with "
              "your hands full. Swipe up and down to move, right to say you "
              "know a word, left to set it aside.</p>"
            + self._audio_toggle()
            + "<div class='card' id='reel'>"
            + video.player(row["video"], 0)
            + f"<div id='reel-board'>{self._scoreboard(row)}</div>"
            + f"<div id='reel-panel'>"
            + self._to_follow(source, row, back=f"/reels?i={here}")
            + "</div></div>"
            + f"<div class='pager'>{prev}{nxt}</div>"
            # State as data, never interpolated into code: the title is a
            # video title and goes nowhere near a script body.
            + "<script type='application/json' id='reel-state'>"
            + state.replace("<", "\\u003c") + "</script>"
            + video.merged_script()
        )
        return layout("Reels", body, "/reels", source)

    def reels_json(self, query: dict) -> dict:
        """One reel's worth of data, for swapping in without a page load.

        The player is deliberately not part of this. Reloading the page to
        change video destroys the iframe, and iOS grants playback permission
        to the iframe's *document* — so the next `playVideo` after a teardown
        is an unprivileged call and simply does nothing. The picture has to
        outlive the swipe, which means the server sends what changes around
        it and the client keeps the player.
        """
        source = self.source(query)
        ranked = self._watchable(source)
        if not ranked:
            return {"empty": True}
        here = min(max(int(query.get("i") or 0), 0), len(ranked) - 1)
        row = ranked[here]
        return {
            "at": here,
            "total": len(ranked),
            "video": row["video"],
            "title": row["title"] or row["video"],
            "scoreboard": self._scoreboard(row),
            "panel": self._to_follow(source, row, back=f"/reels?i={here}"),
        }

    @staticmethod
    def _scoreboard(row: dict) -> str:
        length = f"{row['minutes']:.0f} min" if row["minutes"] else "unknown"
        cells = (("you can follow", f"{row['comprehension']:.0%}"),
                 ("length", length),
                 ("sentences", f"{row['lines']:,}"),
                 ("one new thing", f"{row['i+1']:,}"),
                 ("teaches from your list", f"{row['teaches']:,}"),
                 ("watchability", f"{row['watch']:.2f}"))
        return ("<div class='switch'>" + "".join(
            f"<span><strong>{value}</strong> {label}</span>" for label, value in cells
        ) + "</div>")

    def _to_follow(self, source: str, row: dict, back: str = "/reels",
                   limit: int = 8) -> str:
        """The words that would make the most of *this* video readable.

        Not the roadmap's next step, which answers a different question —
        what is most useful across everything you are learning. Here the
        question is narrower and more satisfying: this video, right now, what
        single word buys the most of it.

        A word's gain is the number of sentences in which it is the *only*
        unknown, because those are the ones that become readable the moment
        you learn it. Sentences with two unknowns are not counted: they need
        both, and crediting either one would promise a gain that learning it
        does not deliver.
        """
        gain = Counter({Unit(kind, key): n for kind, key, n in row.get("next", [])})
        if not gain:
            return ("<p class='note'>Nothing here is one word away — every "
                    "sentence you cannot read needs two or more.</p>")

        goals = frozenset(self.app.goal_units)
        total = max(row["lines"], 1)
        at = row["comprehension"]
        # The first entry is what a sideways swipe takes, so it says so. The
        # panel lists eight and the gesture is silent about which — swiping
        # blind into a permanent change to your vocabulary is not a thing to
        # ask anyone to do.
        entries = "".join(
            "<div class='entry{}'><div class='rail'>+{:.0%}<span class='kind'>{}</span>"
            "</div><div class='body'><div class='unit'>"
            "<a href='/unit/{}/{}?src={}'>{}</a></div>"
            "<p class='also'>{} more sentence{} in this video readable"
            "{}</p>{}</div></div>".format(
                " target" if n == 0 else "",
                count / total,
                "on your list" if unit in goals else "extra",
                unit.kind, quote(unit.key, safe=""), quote(source),
                escape(unit.key), count, "" if count == 1 else "s",
                f" — {at:.0%} to {(at + count / total):.0%}" if count else "",
                self._word_actions(unit, source, back))
            for n, (unit, count) in enumerate(gain.most_common(limit)))
        best = gain.most_common(1)[0]
        return (f"<h2>Learn next to follow this one</h2>"
                f"<p class='note'>{len(gain):,} words here are a single step "
                f"away. <strong>{escape(best[0].key)}</strong> buys the most: "
                f"{best[1]} sentence{'' if best[1] == 1 else 's'}, "
                f"taking you from {at:.0%} to "
                f"{(at + best[1] / total):.0%}.</p>"
                f"<div class='ledger'>{entries}</div>")

    def _watchable(self, source: str, floor: int = ENOUGH_LINES) -> list[dict]:
        """Every video with enough in it, best-to-watch first.

        `floor` is what the reel refuses to offer; the catalogue lists
        everything and lets the score speak, since a thin video is not
        hidden, it simply sinks.

        Serialised, because the server answers requests on threads and this
        is expensive exactly when the cache is empty. Two page loads on a
        cold start would each load the corpus and score every video — a
        gigabyte and a minute apiece, twice, to produce the same rows.

        Every video is scored and stored; `floor` filters on the way out.
        Storing the filtered list instead would let whichever page asked
        first decide what the other one sees — the catalogue would show the
        reel's 713 rather than its own 893.

        Read from the database when the stamp still matches, so a restart
        costs nothing. When it does not, everything is scored once and
        stored; marking a word takes the cheaper path in `mark_known`.
        """
        rows = self._ranked.get(source)
        if rows is None:
            with self._scoring:
                # Checked again inside the lock: by the time a waiting
                # request gets in, the one it was waiting for has usually
                # already done the work, and repeating it is the whole thing
                # the lock exists to prevent.
                rows = self._ranked.get(source)
                if rows is None:
                    rows = self._compute(source)
                    self._ranked[source] = rows
        return [r for r in rows if r["lines"] >= floor]

    def _compute(self, source: str) -> list[dict]:
        """Stored scores if they still describe you, otherwise scored afresh."""
        stamp = self._score_stamp()
        rows = self._scores.load(source, stamp)
        if rows is not None:
            return rows
        known, goals = self.known, frozenset(self.app.goal_units)
        rows = sorted((self._score_video(v, s, known, goals)
                       for v, s in self._grouped(source).items()),
                      key=lambda r: -r["watch"])
        self._scores.save(source, stamp, rows)
        return rows

    def _score_video(self, video_id: str, sentences: list, known, goals) -> dict:
        """One video against one known set.

        The next-best words fall out of the same pass: a sentence with one
        unknown is both what makes the video teachable and the evidence for
        which word to learn. Counting them and discarding which ones they
        were is what forced the reel to load the whole corpus again to
        rebuild an answer it had already computed.
        """
        readable = teachable = 0
        unblocks: set = set()
        gain: Counter = Counter()
        for sentence in sentences:
            missing = sentence.units - known
            if not missing:
                readable += 1
            elif len(missing) == 1:
                teachable += 1
                unit = next(iter(missing))
                gain[unit] += 1
                if unit in goals:
                    unblocks.add(unit)
        comprehension = readable / len(sentences)
        minutes = self._minutes().get(video_id)
        return {"video": video_id, "title": self._titles().get(video_id, ""),
                "lines": len(sentences), "minutes": minutes,
                "comprehension": comprehension, "i+1": teachable,
                "teaches": len(unblocks),
                "watch": watchability(comprehension, minutes, len(sentences)),
                # Enough to show, not the whole tail: the panel lists eight.
                "next": [(u.kind, u.key, n) for u, n in gain.most_common(NEXT_WORDS)]}

    def _videos_with(self, source: str) -> dict:
        """Unit -> the videos that say it.

        The index that makes marking a word cheap: a word you have just
        learned cannot change the score of a video that never says it.
        """
        if source not in self._unit_videos:
            index: dict = defaultdict(set)
            for video_id, sentences in self._grouped(source).items():
                for sentence in sentences:
                    for unit in sentence.units:
                        index[unit].add(video_id)
            self._unit_videos[source] = index
        return self._unit_videos[source]

    def _unmark(self, unit: Unit) -> str:
        """Take back "I know this".

        The only destructive thing this app does, and until now the only one
        with no way back: `KnownStore.remove` existed and nothing called it.
        A right swipe is a gesture you make hundreds of times and will
        sometimes make by accident.

        What cannot be undone in place is dropped instead. `KnownSet.learn`
        and `CorpusIndex.learn` both only go forwards — an index is built to
        move sentences down states, never up — so rather than pretend
        otherwise, the caches holding them are thrown away and rebuilt. That
        costs a corpus load on the next page that needs one, which is the
        right price for an action taken once in a session.

        The card comes back too. It was deleted on the assumption you knew
        the word; taking that back should put it in the queue again rather
        than quietly losing its place.
        """
        self.app.marked_known.remove(unit)
        self.app.card_store.add_many(
            [self.app.scheduler.new_card(unit, datetime.now())])
        self._known = None
        self._scopes.clear()
        self._stuck.clear()
        self._queue_rescore(unit)
        return unit.key

    def _queue_rescore(self, unit: Unit) -> None:
        """Hand the word to the scorer and get out of the way.

        The stamp is what keeps this honest. It carries the known-set version,
        so between the POST returning and the worker finishing, what is on
        disk simply disagrees with what the reader knows — and a disagreeing
        stamp means recompute, never serve. The window is a few seconds and it
        errs in the safe direction.
        """
        self._marks.put(unit)
        if self._worker is None or not self._worker.is_alive():
            self._worker = Thread(target=self._drain, name="rescore",
                                  daemon=True)
            self._worker.start()

    def _drain(self) -> None:
        """One at a time, forever. Daemon, so it never holds up a shutdown."""
        while True:
            unit = self._marks.get()
            try:
                self._rescore(unit)
            except Exception as error:            # noqa: BLE001
                # Printed here rather than through `web.server._report`,
                # which cannot be imported this way round — server imports
                # handlers. Swallowed either way: a worker that dies takes
                # every later mark with it, silently, because nothing is left
                # draining the queue.
                import traceback
                print(f"\n--- rescoring {unit.kind}:{unit.key} failed ---",
                      flush=True)
                traceback.print_exception(error)
            finally:
                self._marks.task_done()

    def _rescore(self, unit: Unit) -> None:
        """Update only the videos that say `unit`.

        Rescoring everything took sixty-eight seconds, which is not a price
        worth paying for one word — and it is mostly wasted, since a video
        that never says the word scores exactly as it did. The stamp still
        guards correctness: if this ever misses a video, the fingerprint
        stops matching and the next read rebuilds the lot.

        Serialised on the same lock `_watchable` uses, because `_grouped`
        below materialises the whole corpus on a cold cache and two quick
        taps would otherwise run two of those at once — a gigabyte apiece, on
        request threads. The lock is not reentrant; this is reached only from
        `mark_known`, which holds nothing.
        """
        with self._scoring:
            self._rescore_locked(unit)

    def _rescore_locked(self, unit: Unit) -> None:
        known, goals = self.known, frozenset(self.app.goal_units)
        stamp = self._score_stamp()
        for source, rows in list(self._ranked.items()):
            touched = self._videos_with(source).get(unit, set())
            if not touched:
                self._scores.restamp(source, stamp)
                continue
            # Every video, not the filtered view. `_ranked` once held only
            # what cleared the reel's floor, so an update could write rows
            # for videos the list had never heard of — and memory and disk
            # then disagreed about which videos exist.
            grouped = self._grouped(source)
            fresh = {v: self._score_video(v, grouped[v], known, goals)
                     for v in touched if v in grouped}
            rows = sorted((fresh.get(r["video"], r) for r in rows),
                          key=lambda r: -r["watch"])
            self._ranked[source] = rows
            self._scores.update(source, stamp, list(fresh.values()))

    def _score_stamp(self) -> str:
        """What the stored scores were computed against.

        The analyser, because a rebuilt corpus says different things; the
        known-set version, which the database bumps itself whenever a word is
        marked; and `SCORE_VERSION`, because the scoring code is an input
        too. Leaving that out already served stale rows once: a change to
        which videos get scored left nine hundred rows that said seven
        hundred, under a stamp that still matched.
        """
        return (f"{analyser_fingerprint()}|{SCORE_VERSION}"
                f"|{self.app.marked_known.version()}")

    def _grouped(self, source: str) -> dict[str, list]:
        """Sentences by video. Cached: it does not depend on what you know.

        Counted the way the strict roadmap counts. Every word in the line
        counts against comprehension, which is what makes a percentage about
        a video mean anything — but the bare lemma the analyser yields beside
        the goal that already teaches it is one word arriving twice, and
        counting it said you did not know `passieren` while the roadmap was
        telling you that you did.

        It was worth 1.9 points of comprehension across the corpus and moved
        591 of 893 videos, and it mattered more to the next-best-word panel:
        the sentences one word away went from 24,676 to 31,105, a quarter of
        the evidence that panel reasons from.
        """
        if source not in self._videos:
            groups: dict[str, list] = defaultdict(list)
            for sentence in self.app.corpus(*self._builds(source), strict=True):
                if sentence.timing:
                    groups[sentence.timing.video_id].append(sentence)
            self._videos[source] = dict(groups)
        return self._videos[source]

    def _minutes(self) -> dict[str, float]:
        if self._durations is None:
            with Database(self.app.settings.own) as db:
                rows = db.rows("SELECT video_id, duration FROM video"
                               " WHERE duration IS NOT NULL")
            self._durations = {v: secs / 60 for v, secs in rows}
        return self._durations

    def _titles(self) -> dict[str, str]:
        if self._video_titles is None:
            with Database(self.app.settings.own) as db:
                self._video_titles = dict(
                    db.rows("SELECT video_id, title FROM video"))
        return self._video_titles

    def watch(self, query: dict) -> str:
        source = self.source(query)
        target = Unit(query.get("kind", ""), query.get("key", ""))
        list_only = self.counting(query)
        holding = self.app.corpus(*self._builds(source), list_only=list_only,
                                  strict=not list_only,
                                  holding=(target.kind, target.key))
        clips = [s for s in ExampleIndex(holding).examples(
                     target, self.known, limit=60) if s.timing]
        if not clips:
            return layout("Watch", self.switch(source, "/") +
                          "<h1>Nothing to watch</h1><p class='empty'>No video "
                          "sentence in this corpus uses that.</p>", "/", source)

        i = min(max(int(query.get("i") or 0), 0), len(clips) - 1)
        clip = clips[i]
        cues = self._cues(clip.timing.video_id)
        here = min(range(len(cues)),
                   key=lambda n: abs(cues[n].timing.start - clip.timing.start))
        surface = clip.surface_of(target)

        args = (f"src={quote(source)}&kind={quote(target.kind)}"
                f"&key={quote(target.key, safe='')}")
        prev = (f"<a href='/watch?{args}&i={i - 1}'>previous</a>" if i else "")
        nxt = (f"<a href='/watch?{args}&i={i + 1}'>next</a>"
               if i + 1 < len(clips) else "")
        body = (
            f"<h1>{escape(target.key)}</h1>"
            f"<p class='occurrence'>Occurrence {i + 1} of {len(clips)} in these "
            "videos. The transcript follows the video; click any line to jump.</p>"
            + video.player(clip.timing.video_id, clip.timing.start)
            + video.caption(clip.text, clip.translation, surface)
            + f"<div class='pager'>{prev}{nxt}</div>"
            + self._actions(target, source, "/")
            + "<h2>Transcript</h2>"
            + video.transcript(cues, here, surface)
            + video.script()
        )
        return layout(f"{target.key} on video", body, "/subtitles", source)

    def _cues(self, video_id: str) -> list[Sentence]:
        """Every line of one video, in the order it is spoken.

        Asked of the database rather than of the corpus. This used to load
        every sentence of both builds and keep the two hundred with the right
        video id, which is a full scan and a million interned units for a
        panel that fires on its own the moment the reading page opens.
        """
        cues = [s for s in self.app.corpus_store.load(
                    "subtitle", "subtitle:llm", teachable_only=False,
                    video=video_id)
                if s.timing]
        return sorted(cues, key=lambda s: s.timing.start)

    def subtitles(self, query: dict) -> str:
        source = self.source(query)
        # Scored the same way the Reels tab ranks them, off the same grouping,
        # so the catalogue answers the question you actually have about a
        # video — can I follow it — and does not pay to load the corpus twice.
        # Length comes off the scored row, not from Postgres. `_minutes()`
        # was called here unconditionally and was the one thing on a warm page
        # that still needed a database — for a number `video_score` already
        # holds, which is how /reels renders it without asking anyone.
        ranked = self._watchable(source, floor=1)
        order = query.get("by") or "watch"
        plan = self._video_plan.order(source) if order == "plan" else {}
        if order == "plan" and not plan:
            order = "watch"          # nothing built yet; say the true order
        ranked = self._ordered(ranked, order, plan)
        # Reels is indexed by the watchability order, so a link from a
        # re-sorted table has to name the video rather than its row here.
        by_video = {r["video"]: n for n, r in
                    enumerate(self._ordered(ranked, "watch"))}
        rows = "".join(
            f"<tr><td><a href='/reels?src={quote(source)}"
            f"&i={by_video.get(r['video'], 0)}'>"
            f"{escape((r['title'] or r['video'])[:58])}</a></td>"
            f"<td class='n'>{r['comprehension']:.0%}</td>"
            f"<td class='n'>{r['watch']:.2f}</td>"
            f"<td class='n'>{self._density(r):.1f}</td>"
            f"<td class='n'>{r['teaches']:,}</td>"
            f"<td class='n'>{r['lines']:,}</td>"
            f"<td class='n'>"
            + (f"{r['minutes']:.0f} min" if r["minutes"] is not None else "—")
            + "</td></tr>"
            for r in ranked
        )
        table = (f"<table class='rows'><tr><th>video</th>"
                 f"<th class='n'>you follow</th><th class='n'>watch</th>"
                 f"<th class='n'>i+1/min</th>"
                 f"<th class='n'>teaches</th><th class='n'>cues</th>"
                 f"<th class='n'>length</th></tr>{rows}</table>" if rows
                 else "<p class='empty'>No aligned subtitles yet.</p>")
        picker = "".join(
            f"<a href='/subtitles?src={quote(source)}"
            + (f"&by={value}" if value != "watch" else "")
            + f"' class='{'on' if order == value else ''}'>{label}</a>"
            for value, label in (("watch", "easiest to follow"),
                                 ("density", "most to learn per minute"),
                                 ("teaching", "most of your list per minute"),
                                 ("plan", "in order, each building on the last"))
        )
        body = ("<h1>Videos</h1>"
                f"<div class='switch'><span>Best first</span>{picker}</div>"
                "<p class='note'><em>You follow</em> is the share of its "
                "sentences you can already read, and <em>watch</em> combines "
                "that with length. Those favour videos you understand "
                "already. <em>i+1/min</em> asks the opposite question — how "
                "much this video could teach you per minute — and picks "
                "almost entirely different films: of the top fifty by each, "
                "two are the same. Both move as you mark words known. "
                "<em>In order</em> is different again — a plan rather than a "
                "ranking, where each video is scored against what the ones "
                "before it taught you, so it does not change as you watch."
                "</p>"
                + self._add_video_form(query)
                + f"<h2>{len(ranked)} in the catalogue</h2>" + table)
        return layout("Videos", body, "/subtitles", source)

    @staticmethod
    def _density(row: dict) -> float:
        """Sentences one word away, per minute.

        The teaching rate: how much of this video is material you could
        actually learn from, rather than how comfortable it is to sit
        through. A video with no length recorded scores nothing rather than
        dividing by a guess.
        """
        return row["i+1"] / row["minutes"] if row.get("minutes") else 0.0

    def _ordered(self, rows: list[dict], order: str,
                 plan: dict[str, int] | None = None) -> list[dict]:
        """The catalogue, best first by whichever question was asked.

        `watch` and the two rates disagree almost completely — they are not
        two views of one ranking but answers to different questions, and the
        page says so rather than presenting one as the truth.
        """
        if order == "plan" and plan:
            # Videos the walk left out teach nothing at this point, so they go
            # after everything it planned rather than being hidden.
            return sorted(rows, key=lambda r: plan.get(r["video"], 10 ** 9))
        if order == "density":
            return sorted(rows, key=self._density, reverse=True)
        if order == "teaching":
            return sorted(rows, key=lambda r: (r["teaches"] / r["minutes"]
                                               if r.get("minutes") else 0.0),
                          reverse=True)
        return sorted(rows, key=lambda r: -r["watch"])

    @staticmethod
    def _add_video_form(query: dict) -> str:
        """Paste a video in. Says what it is about to do, because unlike every
        other button here this one reaches out to YouTube and then writes to
        the catalogue."""
        said = ""
        if query.get("added"):
            said = (f"<p class='note said'>Added "
                    f"<strong>{escape(query['added'])}</strong>. "
                    "Analysed and folded into the roadmap already.</p>")
        elif query.get("problem"):
            said = (f"<p class='note said bad'>{escape(query['problem'])}</p>")
        return (
            said +
            "<form class='bar' method='post' action='/add-video'>"
            "<input type='text' name='video' autocomplete='off' "
            "placeholder='a YouTube link, or just the video id'>"
            "<button class='go' type='submit'>Add video</button>"
            "</form>"
            "<form class='bar' method='post' action='/add-channel'>"
            "<input type='text' name='channel' autocomplete='off' "
            "placeholder='a channel: UC… id, @handle, or channel URL'>"
            "<input type='number' name='limit' value='8' min='1' max='40' "
            "style='width:5.5rem' title='how many videos to take'>"
            "<button class='go' type='submit'>Add channel</button>"
            "</form>"
            "<p class='note'>Both fetch German subtitles and write them to the "
            "catalogue, then fold the result into the roadmap. The page "
            "waits — about a minute for a video, a few for a channel, which is "
            "why a channel is capped.</p>"
        )

    def add_channel(self, form: dict) -> str:
        """Take some of a channel, and say where to go next either way.

        Capped on purpose. A German channel can hold hundreds of videos and
        each is a fetch of several seconds; a browser waiting half an hour on
        one POST is a worse way to spend that time than the command line,
        which is what the cap points people towards.
        """
        from corpus import CorpusUpdater
        from ingest import ChannelLister, VideoIngestor
        from roadmap import RoadmapRefresher

        given = (form.get("channel") or "").strip()
        if not given:
            return "/subtitles?problem=Paste+a+channel+id%2C+handle+or+URL+first."
        try:
            limit = max(1, min(int(form.get("limit") or 8), 40))
        except ValueError:
            limit = 8

        try:
            lister = ChannelLister()
            channel = lister.identify(given)
            ingestor = VideoIngestor(self.app.settings, self.app.analyzer)
            wanted = [v for v in lister.videos(channel, limit * 3)
                      if not ingestor.already_have(v)][:limit]
        except SystemExit as refused:
            return f"/subtitles?problem={quote(str(refused))}"
        except Exception as error:               # noqa: BLE001 — report, don't 500
            return f"/subtitles?problem={quote(f'{type(error).__name__}: {error}')}"

        if not wanted:
            # Built before the f-string rather than inside it: an expression
            # spanning lines inside the braces is PEP 701, which means Python
            # 3.12, and nothing else here needs a version that new.
            note = (channel + " has nothing new — everything it lists is "
                    "already in the catalogue.")
            return f"/subtitles?problem={quote(note)}"

        added, refused = [], 0
        for video_id in wanted:
            try:
                added.append(ingestor.add(video_id))
            except Exception:                    # noqa: BLE001 — one bad video
                refused += 1

        if not added:
            note = (f"{channel}: none of the {len(wanted)} tried had manual "
                    "German subtitles.")
            return f"/subtitles?problem={quote(note)}"

        caught = CorpusUpdater(self.app).catch_up()
        self._sources = None            # a build just changed size
        rebuilt = RoadmapRefresher(self.app).refresh(touching="subtitle")
        self._scopes.clear()
        self._stuck.clear()
        done = (f"{channel} — {len(added)} videos, {caught.teachable} sentences"
                + (f", {refused} skipped" if refused else "")
                + (f", roadmap now {max(rebuilt.values())} steps" if rebuilt else ""))
        return f"/subtitles?added={quote(done)}"

    def add_video(self, form: dict) -> str:
        """Scrape one video, and say where to go next either way.

        Returns a URL rather than a page: a write wants a redirect after it,
        so a refresh does not scrape the same video twice.
        """
        from commands.add_video import AddVideoCommand
        from ingest import VideoIngestor

        given = (form.get("video") or "").strip()
        if not given:
            return "/subtitles?problem=Paste+a+video+link+or+id+first."
        try:
            video_id = AddVideoCommand._identify(given)
            ingestor = VideoIngestor(self.app.settings, self.app.analyzer)
            if ingestor.already_have(video_id):
                return f"/subtitles?problem={quote(video_id + ' is already in the catalogue.')}"
            landed = ingestor.add(video_id)
        except SystemExit as refused:            # the ingestor's own reasons
            return f"/subtitles?problem={quote(str(refused))}"
        except Exception as error:               # noqa: BLE001 — report, don't 500
            return f"/subtitles?problem={quote(f'{type(error).__name__}: {error}')}"

        # Finish the job rather than telling them to. Only the new video is
        # analysed, and only roadmaps over the subtitles are rebuilt.
        from corpus import CorpusUpdater
        from roadmap import RoadmapRefresher
        caught = CorpusUpdater(self.app).catch_up()
        self._sources = None            # a build just changed size
        rebuilt = RoadmapRefresher(self.app).refresh(touching="subtitle")
        self._scopes.clear()          # what is in memory no longer matches
        self._stuck.clear()
        done = (f"{landed.title} — {caught.teachable} sentences added"
                + (f", roadmap now {max(rebuilt.values())} steps" if rebuilt else ""))
        return f"/subtitles?added={quote(done)}"

    # --- bits -------------------------------------------------------------

    @staticmethod
    def _filters(needle: str, kind: str, source: str, hide: str = "") -> str:
        options = "".join(
            f"<option value='{v}'{' selected' if kind == v else ''}>{label}</option>"
            for v, label in (("", "words and patterns"), ("word", "words only"),
                             ("pattern", "patterns only")))
        shown = "".join(
            f"<option value='{v}'{' selected' if hide == v else ''}>{label}</option>"
            for v, label in (("", "everything"), ("known", "only what is left")))
        return ("<form class='bar' method='get' action='/roadmap'>"
                f"<input type='hidden' name='src' value='{escape(source)}'>"
                f"<input type='text' name='q' value='{escape(needle)}' "
                "placeholder='a word, a pattern, or something in a sentence'>"
                f"<select name='kind'>{options}</select>"
                f"<select name='hide'>{shown}</select>"
                "<button type='submit'>Filter</button></form>")

    @staticmethod
    def _pager(page: int, pages: int, needle: str, kind: str, source: str,
               hide: str = "") -> str:
        tail = (f"&q={quote(needle)}&kind={quote(kind)}&src={quote(source)}"
                f"&hide={quote(hide)}")
        back = (f"<a href='/roadmap?page={page - 1}{tail}'>previous</a>"
                if page > 1 else "")
        fwd = (f"<a href='/roadmap?page={page + 1}{tail}'>next</a>"
               if page < pages else "")
        return (f"<div class='pager'>{back}"
                f"<span class='quiet'>page {page} of {pages}</span>{fwd}</div>")


def _hunt_term(unit: Unit) -> str:
    """What to look the unit up as.

    A pattern is a frame — "jdm. (Dat) etw. (Akk) geben" — and no one
    searches for that. Its last word is the verb it hangs on, which is what
    a lookup site indexes.
    """
    return unit.key.split()[-1] if unit.is_pattern else unit.key


def _clock(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"

