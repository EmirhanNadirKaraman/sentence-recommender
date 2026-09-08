"""What each page shows.

The viewer answers "what is i+1 *right now*" from a live index rather than
from a stored roadmap, so marking a word known takes effect on the next page
load. The stored roadmap remains the planned curriculum for the CLI; this is
the reader's moving position in it.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from html import escape
from urllib.parse import quote

from corpus.sentence import Sentence
from roadmap import (
    CorpusIndex, ExampleIndex, KnownSet, RoadmapBuilder, UnitPriority,
)
from roadmap.store import ALL, RoadmapStore
from vocab.entry import LEMMA, PATTERN, Unit
from web import watch as video
from web.render import layout, sentence

PAGE_SIZE = 40

# How many alternative i+1 sentences to carry for one unit. Enough to find a
# readable one, few enough that the page stays small.
DECK_SIZE = 24

# Ceiling on the exhaustive walk behind the blocked list, so a large corpus
# cannot hang the page.
WALK_LIMIT = 5000
PREFERRED = ("subtitle", "subtitle:llm", ALL)
LABELS = {ALL: "everything", "subtitle": "video subtitles",
          "subtitle:llm": "video subtitles, model-corrected",
          "tatoeba": "Tatoeba"}


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
        # Units set aside without claiming to know them. Session-only: the
        # card in the review queue is the durable record, this just stops the
        # page offering the same thing again.
        self._passed: set[Unit] = set()
        # Blocked-set results, per source. The walk behind them is cheap on a
        # subtitle corpus and slow on a quarter of a million sentences.
        self._stuck: dict[str, list] = {}

    # --- scope ------------------------------------------------------------

    def sources(self) -> dict[str, int]:
        known = self.app.corpus_store.builds(teachable_only=True)
        out = {name: count for name, count in known.items()}
        if len(out) > 1:
            out[ALL] = sum(out.values())
        return out

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
        """Whether to count only what the study list names. Default yes —
        the list is what the reader set out to learn."""
        return (query.get("count") or "list") == "list"

    def scope(self, source: str, list_only: bool = True) -> Scope:
        """The live index for one corpus, built once and kept current.

        Keyed by counting mode as well as corpus: narrowing to the study list
        gives genuinely different unknown counts, so the two cannot share.
        """
        key = f"{source}|{'list' if list_only else 'all'}"
        if key not in self._scopes:
            sentences = self.app.corpus(*self._builds(source),
                                        list_only=list_only)
            # The resolved vocabulary, not a fresh resolution: known_set()
            # re-runs the parser over every word in the files, which is
            # sixteen seconds, and this viewer already holds the answer.
            index = CorpusIndex(sentences, KnownSet(self.known))
            priority = self.app.priority()
            self._scopes[key] = Scope(
                sentences=sentences,
                index=index,
                builder=RoadmapBuilder(index, priority,
                                       self.app.settings.priority_weight),
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
            for value, label in (("list", "only my study list"),
                                 ("all", "every word it finds"))
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
        scope = self.scope(source, self.counting(query))
        only = query.get("only") or ""
        skip = set(self._passed)
        if only == "word":
            # Patterns are grammar, not vocabulary. Some days you want one and
            # not the other, so they can be stepped over without being learned.
            skip |= {u for u in scope.index.known_units_of_kind(PATTERN)}
        step = scope.builder.peek(
            exclude=frozenset(skip),
            kinds=frozenset({LEMMA}) if only == "word" else frozenset(),
        )
        switch = self.switch(source, "/") + self.counting_switch(query, "/")
        picker = self._kind_picker(only, source)

        if step is None:
            body = (switch + picker + "<h1>Nothing left that is i+1</h1>"
                    "<p class='empty'>Every remaining sentence needs two or more "
                    "new things. Widen the filter, add another corpus, or "
                    "<a href='/review'>review what you have</a>.</p>")
            return layout("i+1", body, "/", source)

        unit, surface = step.unit, step.sentence.surface_of(step.unit)
        occurrences = scope.examples.count(unit)
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
            switch + picker +
            f"<h1>{scope.index.readable:,} sentences you can already read</h1>"
            f"<p class='note'>{lede}</p>"
            + self._stage(scope, unit)
            + self._deck(scope, unit, source) +
            "<h2>The new thing</h2>"
            f"<p class='de'>{escape(unit.key)}</p>"
            f"<p class='en'>{kind}, appearing in {occurrences:,} sentence"
            f"{'s' if occurrences != 1 else ''} here and opening {step.gain} "
            f"more</p>"
            + self._actions(unit, source, "/", watchable=self._has_video(scope, unit))
            + ("<h2>Transcript</h2><ol class='transcript' id='transcript'></ol>"
               if self._has_video(scope, unit) else "")
            + video.merged_script()
        )
        return layout("i+1", body, "/", source)

    def _stage(self, scope: Scope, unit: Unit) -> str:
        """The player, opened on the first sentence the deck will show.

        Rendered here rather than behind a link: the point of a subtitle
        corpus is that every sentence was said out loud, so hearing one should
        be the default rather than a second click. Returns nothing when no
        example has a video, which is every Tatoeba sentence.
        """
        first = next((s for s in scope.examples.examples(unit, self.known,
                                                         limit=DECK_SIZE)
                      if s.timing), None)
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

    def _deck(self, scope: Scope, unit: Unit, source: str = "") -> str:
        """Every sentence using `unit`, readable ones first, stepped in place.

        Strictly-i+1 sentences come first because the ranking sorts on how
        much *else* is unknown, and there are often only one or two of them —
        `etw. (Akk) können` appears in 131 subtitle sentences but is the sole
        unknown in one. Stopping there would leave nothing to step through, so
        the rest follow, each saying what else in it is new. That keeps the
        i+1 claim honest while still letting the whole set be read without
        leaving the page.
        """
        known = self.known
        options = scope.examples.examples(unit, known, limit=DECK_SIZE)
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
            "<span class='hint'>arrow keys &nbsp;&nbsp; "
            + (f"{readable} of them need only this"
               if readable != 1 else "one of them needs only this")
            + "</span></div>"
            + _DECK_SCRIPT
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
        found = next((s for s in self.scope(source, False).sentences
                      if s.text == text),
                     None)
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
    def _has_video(scope: Scope, unit: Unit) -> bool:
        return any(s.timing for s in scope.examples.examples(
            unit, frozenset(), limit=40))

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

        if form.get("action") == "pass":
            self._passed.add(unit)
        else:
            self.app.marked_known.add(unit)
            self.app.card_store.remove(unit)
            self._passed.discard(unit)
            if self._known is not None and unit not in self._known:
                self._known.learn(unit)
            for scope in self._scopes.values():
                if unit not in scope.index.known:
                    scope.index.learn(unit)
        return f"{back}?src={quote(source)}" if source else back

    # --- the rest ---------------------------------------------------------

    def roadmap(self, query: dict) -> str:
        source = self.source(query)
        steps = self._store.load(source)
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
            "</div></div>"
            for s in window
        )
        listing = (f"<div class='ledger'>{entries}</div>" if window
                   else "<p class='empty'>Nothing here matches that.</p>")
        body = (self.switch(source, "/roadmap") + "<h1>Roadmap</h1>"
                f"<p class='note'>{len(steps):,} steps in the order they were "
                "planned, saved by the last build. The marked word was the only "
                "unknown one in its sentence at that point — anything you have "
                "learned since is labelled <em>known</em> in the rail.</p>"
                f"{self._filters(needle, kind, source, query.get('hide', ''))}"
                f"{self._hidden_note(hidden)}{listing}"
                f"{self._pager(page, pages, needle, kind, source, query.get('hide', ''))}")
        return layout("Roadmap", body, "/roadmap", source)

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
               f"<p class='also'>{gap} new things in its easiest sentence here: "
               f"{escape(', '.join(rest))}</p>" if example else
               "<p class='also'>Never said in this corpus. Find a clip of it "
               "and the chain continues.</p>")
            + "<div class='tools'>"
            f"<a class='link' target='_blank' rel='noreferrer' "
            f"href='https://de.youglish.com/pronounce/"
            f"{quote(_hunt_term(unit), safe='')}/german'>Find it on YouGlish</a>"
            "</div>"
            "</div></div>"
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
            f"<p class='note'>{len(stranded):,} things this corpus can never "
            "teach you, because none of them is ever the only new thing in a "
            f"sentence. {near:,} are one word away — learn that word, or find a "
            "clip that says this one plainly, and the chain continues.</p>"
            + (f"<div class='ledger'>{entries}</div>" if entries
               else "<p class='empty'>Nothing is stranded — the roadmap "
                    "reaches everything in this corpus.</p>")
            + (f"<p class='note'>Showing the {PAGE_SIZE} most frequent of "
               f"{len(rows):,}.</p>" if len(rows) > PAGE_SIZE else "")
        )
        return layout("Blocked", body, "/blocked", source)

    def _stranded(self, source: str, list_only: bool = True):
        """Units left unknown once the walk runs out, most frequent first.

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
        RoadmapBuilder(spare, scope.priority, self.app.settings.priority_weight
                       ).build(max_steps=WALK_LIMIT)
        reached = spare.known

        appearances: Counter = Counter()
        easiest: dict = {}
        for s in scope.sentences:
            unknown = s.units - reached
            if not unknown:
                continue
            for u in unknown:
                appearances[u] += 1
                if u not in easiest or len(unknown) < easiest[u][0]:
                    easiest[u] = (len(unknown), s.text,
                                  sorted(x.key for x in unknown - {u})[:4])
        rows = [(u, n, *easiest[u]) for u, n in appearances.most_common()]

        # Goals this corpus never says at all. Far more numerous than the
        # ones it says but cannot isolate, and the actual work — so they
        # belong on the page you mine from, not only in the hunt. Anything
        # the analyser has never emitted is left out: no video can fix it.
        producible = self.app.producible
        priority = scope.priority
        rows += [
            (unit, 0, 0, "", [])
            for unit in sorted(
                (u for u in self.app.goal_units
                 if u not in reached and u not in appearances and u in producible),
                key=lambda u: -priority.of(u),
            )
        ]
        self._stuck[key] = rows
        return rows

    def unit(self, kind: str, key: str, query: dict) -> str:
        source = self.source(query)
        target = Unit(kind, key)
        scope = self.scope(source, self.counting(query))
        known = self.known
        found = scope.examples.examples(target, known, limit=25)

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
            f"<p class='note'>{scope.examples.count(target):,} sentences here use "
            "it. The rail counts what else is unknown in each, so the top ones "
            "are the readable ones.</p>"
            + ("<p class='note'>You have marked this known.</p>" if already
               else self._actions(target, source,
                                  f"/unit/{kind}/{quote(key, safe='')}",
                                  watchable=any(s.timing for s in found)))
            + listing
        )
        return layout(key, body, "/roadmap", source)

    def watch(self, query: dict) -> str:
        source = self.source(query)
        target = Unit(query.get("kind", ""), query.get("key", ""))
        scope = self.scope(source, self.counting(query))
        clips = [s for s in scope.examples.examples(target, self.known, limit=60)
                 if s.timing]
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
        cues = [s for s in self.app.corpus_store.load(
                    "subtitle", "subtitle:llm", teachable_only=False)
                if s.timing and s.timing.video_id == video_id]
        return sorted(cues, key=lambda s: s.timing.start)

    def subtitles(self, query: dict) -> str:
        source = self.source(query)
        by_video: dict[str, list] = defaultdict(list)
        for s in self.app.corpus_store.load("subtitle", "subtitle:llm",
                                            teachable_only=False):
            if s.timing:
                by_video[s.timing.video_id].append(s)
        rows = "".join(
            f"<tr><td><a href='https://www.youtube.com/watch?v={escape(v)}'>"
            f"<code>{escape(v)}</code></a></td><td class='n'>{len(g):,}</td>"
            f"<td class='n'>{max(x.timing.end for x in g) / 60:.0f} min</td></tr>"
            for v, g in sorted(by_video.items())
        )
        table = (f"<table class='rows'><tr><th>video</th><th class='n'>cues</th>"
                 f"<th class='n'>length</th></tr>{rows}</table>" if rows
                 else "<p class='empty'>No aligned subtitles yet.</p>")
        body = ("<h1>Videos</h1><p class='note'>Corrected subtitles re-timed to "
                "the video clock. Open a word from the roadmap to watch it being "
                "said.</p>"
                + self._add_video_form(query)
                + f"<h2>{len(by_video)} in the catalogue</h2>" + table)
        return layout("Videos", body, "/subtitles", source)

    @staticmethod
    def _add_video_form(query: dict) -> str:
        """Paste a video in. Says what it is about to do, because unlike every
        other button here this one reaches out to YouTube and then writes to
        the shared catalogue."""
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
            "shared catalogue, then fold the result into the roadmap. The page "
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
            return (f"/subtitles?problem={quote(channel + ' has nothing new — '
                    'everything it lists is already in the catalogue.')}")

        added, refused = [], 0
        for video_id in wanted:
            try:
                added.append(ingestor.add(video_id))
            except Exception:                    # noqa: BLE001 — one bad video
                refused += 1

        if not added:
            return (f"/subtitles?problem={quote(f'{channel}: none of the '
                    f'{len(wanted)} tried had manual German subtitles.')}")

        caught = CorpusUpdater(self.app).catch_up()
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


_DECK_SCRIPT = """
<script>
(function () {
  var slides = document.querySelectorAll('#deck .slide');
  var at = document.getElementById('at');
  var showing = 0;
  if (slides.length < 2) return;

  function show(i) {
    slides[showing].hidden = true;
    showing = (i + slides.length) % slides.length;
    slides[showing].hidden = false;
    at.textContent = showing + 1;
  }

  document.getElementById('prev').onclick = function () { show(showing - 1); };
  document.getElementById('next').onclick = function () { show(showing + 1); };

  document.addEventListener('keydown', function (e) {
    // Never steal the arrows from a field someone is typing in.
    var el = document.activeElement;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
               el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.key === 'ArrowLeft') { show(showing - 1); e.preventDefault(); }
    if (e.key === 'ArrowRight') { show(showing + 1); e.preventDefault(); }
  });
})();
</script>
"""
