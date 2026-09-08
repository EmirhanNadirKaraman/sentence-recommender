"""What each page shows.

The viewer answers "what is i+1 *right now*" from a live index rather than
from a stored roadmap, so marking a word known takes effect on the next page
load. The stored roadmap remains the planned curriculum for the CLI; this is
the reader's moving position in it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from html import escape
from urllib.parse import quote

from corpus.sentence import Sentence
from roadmap import CorpusIndex, ExampleIndex, RoadmapBuilder, UnitPriority
from roadmap.store import ALL, RoadmapStore
from vocab.entry import LEMMA, PATTERN, Unit
from web import watch as video
from web.render import layout, sentence
from web.review import ReviewSection

PAGE_SIZE = 40

# How many alternative i+1 sentences to carry for one unit. Enough to find a
# readable one, few enough that the page stays small.
DECK_SIZE = 24
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


class Viewer:
    def __init__(self, app) -> None:
        self.app = app
        self._known = None
        self._scopes: dict[str, Scope] = {}
        self._store = RoadmapStore(app.settings.state_path)
        self._review = ReviewSection(self)
        # Units set aside without claiming to know them. Session-only: the
        # card in the review queue is the durable record, this just stops the
        # page offering the same thing again.
        self._passed: set[Unit] = set()

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

    def scope(self, source: str) -> Scope:
        """The live index for one corpus, built once and kept current."""
        if source not in self._scopes:
            sentences = self.app.corpus(*self._builds(source))
            known = self.app.known_set()
            index = CorpusIndex(sentences, known)
            priority = UnitPriority.build(self.app.priority_surfaces(), sentences)
            self._scopes[source] = Scope(
                sentences=sentences,
                index=index,
                builder=RoadmapBuilder(index, priority,
                                       self.app.settings.priority_weight),
                examples=ExampleIndex(sentences),
            )
        return self._scopes[source]

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
        scope = self.scope(source)
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
        switch = self.switch(source, "/")
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
            + self._deck(scope, unit) +
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

    def _deck(self, scope: Scope, unit: Unit) -> str:
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
            f"{self._also_new(s, unit, known)}</div>"
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
                f"<p class='note'>{len(steps):,} steps as they were planned. "
                "The marked word is the only unknown one in its sentence.</p>"
                f"{self._filters(needle, kind, source)}{listing}"
                f"{self._pager(page, pages, needle, kind, source)}")
        return layout("Roadmap", body, "/roadmap", source)

    def unit(self, kind: str, key: str, query: dict) -> str:
        source = self.source(query)
        target = Unit(kind, key)
        scope = self.scope(source)
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
        scope = self.scope(source)
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
                "said.</p>" + table)
        return layout("Videos", body, "/subtitles", source)

    # --- review delegates -------------------------------------------------

    def review(self, query: dict, verdict: str = "") -> str:
        return self._review.page(query, verdict)

    def grade(self, form: dict) -> str:
        return self._review.grade(form)

    # --- bits -------------------------------------------------------------

    @staticmethod
    def _filters(needle: str, kind: str, source: str) -> str:
        options = "".join(
            f"<option value='{v}'{' selected' if kind == v else ''}>{label}</option>"
            for v, label in (("", "words and patterns"), ("word", "words only"),
                             ("pattern", "patterns only")))
        return ("<form class='bar' method='get' action='/roadmap'>"
                f"<input type='hidden' name='src' value='{escape(source)}'>"
                f"<input type='text' name='q' value='{escape(needle)}' "
                "placeholder='a word, a pattern, or something in a sentence'>"
                f"<select name='kind'>{options}</select>"
                "<button type='submit'>Filter</button></form>")

    @staticmethod
    def _pager(page: int, pages: int, needle: str, kind: str, source: str) -> str:
        tail = f"&q={quote(needle)}&kind={quote(kind)}&src={quote(source)}"
        back = (f"<a href='/roadmap?page={page - 1}{tail}'>previous</a>"
                if page > 1 else "")
        fwd = (f"<a href='/roadmap?page={page + 1}{tail}'>next</a>"
               if page < pages else "")
        return (f"<div class='pager'>{back}"
                f"<span class='quiet'>page {page} of {pages}</span>{fwd}</div>")


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
