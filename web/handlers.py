"""What each page shows.

One method per route. Handlers return finished HTML; the server does the
sockets and nothing else.

Everything is scoped to a source — the roadmap over the video subtitles and
the one over everything are different curricula, and the examples shown
alongside a card should come from whichever you are actually studying.
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from datetime import datetime
from html import escape
from urllib.parse import quote

from roadmap import ExampleIndex, RoadmapStore
from roadmap.store import ALL
from srs import PromptBuilder, SM2Scheduler
from vocab.entry import Unit
from web.render import layout, mark, sentence

PAGE_SIZE = 40

# Which roadmap to open on when none is asked for. Subtitles first: they are
# real spoken German, and that is what most people build this to study.
PREFERRED = ("subtitle", "subtitle:llm", ALL)

LABELS = {ALL: "everything", "subtitle": "video subtitles",
          "subtitle:llm": "video subtitles, model-corrected",
          "tatoeba": "Tatoeba"}


class Viewer:
    """Reads the built results and renders them."""

    def __init__(self, app) -> None:
        self._app = app
        self._known = None
        self._examples: dict[str, ExampleIndex] = {}
        self._scheduler = SM2Scheduler()
        self._store = RoadmapStore(app.settings.state_path)

    # --- scope ------------------------------------------------------------

    def sources(self) -> dict[str, int]:
        return self._store.sources()

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
            self._known = self._app.known_set().units
        return self._known

    def examples(self, source: str) -> ExampleIndex:
        if source not in self._examples:
            self._examples[source] = ExampleIndex(
                self._app.corpus(*self._builds(source))
            )
        return self._examples[source]

    def _switch(self, source: str, page: str) -> str:
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

    # --- pages ------------------------------------------------------------

    def next_up(self, query: dict) -> str:
        source = self.source(query)
        steps = self._store.load(source)
        if not steps:
            return layout("i+1", self._switch(source, "/") +
                          "<h1>Nothing mapped yet</h1><p class='empty'>Run "
                          "<code>python main.py build-roadmap</code> to lay out a "
                          "roadmap over this corpus.</p>", "/", source)

        step = self._next_step(steps)
        if step is None:
            body = (self._switch(source, "/") + "<h1>All caught up</h1>"
                    f"<p class='empty'>Every one of the {len(steps):,} steps on "
                    "this roadmap has been answered at least once. Map further "
                    "with <code>build-roadmap --steps</code>.</p>")
            return layout("i+1", body, "/", source)
        builds = self._app.corpus_store.builds(teachable_only=True)
        counted = sum(builds.get(b, 0)
                      for b in (self._builds(source) or builds))
        total, due = self._app.card_store.counts(datetime.now())

        head = (f"<h1>Step {step.position} of {len(steps)}</h1>"
                f"<p class='note'>Everything in this sentence is already yours "
                f"except one thing.</p>")
        body = (
            self._switch(source, "/") + head +
            sentence(step.sentence.text, step.sentence.translation,
                     step.sentence.surface_of(step.unit), lead=True) +
            f"<h2>What it teaches</h2>"
            f"<p class='de'>{escape(step.unit.key)}</p>"
            f"<p class='en'>{'a verb pattern' if step.unit.is_pattern else 'a word'},"
            f" opening {step.gain} more sentence"
            f"{'s' if step.gain != 1 else ''}</p>"
            "<div class='figures'>"
            f"<div><div class='n'>{counted:,}</div><div class='k'>sentences</div></div>"
            f"<div><div class='n'>{len(steps):,}</div><div class='k'>steps mapped</div></div>"
            f"<div><div class='n'>{due:,}</div>"
            f"<div class='k'>of {total:,} cards due</div></div>"
            "</div>"
        )
        return layout("i+1", body, "/", source)

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

        page = max(int(query.get("page") or 1), 1)
        pages = max((len(steps) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        window = steps[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

        entries = "".join(
            "<div class='entry'>"
            f"<div class='rail'>{s.position}"
            f"<span class='kind'>{'pattern' if s.unit.is_pattern else 'word'}</span>"
            "</div><div class='body'>"
            f"<div class='unit'><a href='/unit/{s.unit.kind}/{quote(s.unit.key, safe='')}"
            f"?src={quote(source)}'>{escape(s.unit.key)}</a></div>"
            f"{sentence(s.sentence.text, s.sentence.translation, s.sentence.surface_of(s.unit))}"
            "</div></div>"
            for s in window
        )
        listing = (f"<div class='ledger'>{entries}</div>" if window
                   else "<p class='empty'>Nothing here matches that.</p>")

        body = (
            self._switch(source, "/roadmap") +
            "<h1>Roadmap</h1>"
            f"<p class='note'>{len(steps):,} steps in the order they are taught. "
            "The marked word is the only unknown one in its sentence.</p>"
            f"{self._filters(needle, kind, source)}{listing}"
            f"{self._pager(page, pages, needle, kind, source)}"
        )
        return layout("Roadmap", body, "/roadmap", source)

    def unit(self, kind: str, key: str, query: dict) -> str:
        source = self.source(query)
        target = Unit(kind, key)
        index = self.examples(source)
        found = index.examples(target, self.known, limit=20)

        entries = "".join(
            "<div class='entry'>"
            f"<div class='rail'>{len(s.units - self.known - {target})}"
            "<span class='kind'>unknown</span></div>"
            f"<div class='body'>{sentence(s.text, s.translation, s.surface_of(target))}"
            "</div></div>"
            for s in found
        )
        listing = (f"<div class='ledger'>{entries}</div>" if found
                   else "<p class='empty'>No sentence in this corpus uses it. "
                        "Generate one with <code>python main.py fill-gaps</code>.</p>")

        position = next((s.position for s in self._store.load(source)
                         if s.unit == target), None)
        where = (f"Step {position} of the roadmap." if position
                 else "Not on the roadmap.")
        body = (
            f"<h1>{escape(key)}</h1>"
            f"<p class='note'>{escape(where)} {index.count(target):,} sentences "
            "in this corpus use it. The rail counts what else is unknown in each.</p>"
            f"{listing}"
        )
        return layout(key, body, "/roadmap", source)

    def subtitles(self, query: dict) -> str:
        source = self.source(query)
        by_video: dict[str, list] = defaultdict(list)
        for s in self._app.corpus_store.load("subtitle", "subtitle:llm",
                                             teachable_only=False):
            if s.timing:
                by_video[s.timing.video_id].append(s)

        rows = "".join(
            f"<tr><td><code>{escape(video)}</code></td>"
            f"<td class='n'>{len(group):,}</td>"
            f"<td class='n'>{max(x.timing.end for x in group) / 60:.0f} min</td></tr>"
            for video, group in sorted(by_video.items())
        )
        table = (f"<table class='rows'><tr><th>video</th><th class='n'>cues</th>"
                 f"<th class='n'>length</th></tr>{rows}</table>" if rows
                 else "<p class='empty'>No aligned subtitles yet.</p>")
        body = (
            "<h1>Videos</h1>"
            "<p class='note'>Corrected subtitles, re-timed to the video clock so "
            "they can go back over the picture. Write them out with "
            "<code>python main.py export-subtitles</code>.</p>"
            f"{table}"
        )
        return layout("Videos", body, "/subtitles", source)

    # --- review -----------------------------------------------------------

    def review(self, query: dict, verdict: str = "") -> str:
        source = self.source(query)
        now = datetime.now()
        total, due = self._app.card_store.counts(now)
        cards = self._app.card_store.due(now, limit=1)
        if not cards:
            body = (self._switch(source, "/review") + verdict +
                    "<h1>Nothing due</h1>"
                    f"<p class='empty'>{total:,} cards are scheduled. "
                    "Come back when one comes round, or map more of the roadmap.</p>")
            return layout("Review", body, "/review", source)

        prompt = PromptBuilder(self.examples(source),
                               self._app.settings.examples_per_card
                               ).build(cards[0], self.known)
        body = (self._switch(source, "/review") + verdict +
                self._card(prompt, due, source))
        return layout("Review", body, "/review", source)

    def grade(self, form: dict) -> str:
        source = form.get("src") or ALL
        unit = Unit(form.get("kind", ""), form.get("key", ""))
        card = next((c for c in self._app.card_store.due(datetime.now(), limit=400)
                     if c.unit == unit), None)
        if card is None:
            return self.review({"src": source})

        action = form.get("action", "")
        if action == "skip":
            return self.review({"src": source})
        if action == "reveal":
            prompt = PromptBuilder(self.examples(source),
                                   self._app.settings.examples_per_card
                                   ).build(card, self.known)
            _, due = self._app.card_store.counts(datetime.now())
            return layout("Review",
                          self._switch(source, "/review") +
                          self._card(prompt, due, source, revealed=True),
                          "/review", source)

        if action in ("yes", "no"):
            correct = action == "yes"
        else:
            correct = _fold(form.get("answer", "")) == _fold(unit.key)

        self._app.card_store.save(
            self._scheduler.review(card, correct, datetime.now())
        )
        css = "right" if correct else ""
        word = "Right." if correct else "Not this time."
        verdict = (f"<p class='mark {css}'>{word} "
                   f"<span class='target'>{escape(unit.key)}</span></p>")
        return self.review({"src": source}, verdict)

    def _card(self, prompt, due: int, source: str, revealed: bool = False) -> str:
        unit = prompt.unit
        hidden = (f"<input type='hidden' name='kind' value='{escape(unit.kind)}'>"
                  f"<input type='hidden' name='key' value='{escape(unit.key)}'>"
                  f"<input type='hidden' name='src' value='{escape(source)}'>")
        if prompt.cloze:
            shown = "".join(
                f"<p class='de'>{_blank(line)}</p>" +
                (f"<p class='en'>{escape(x.translation)}</p>" if x.translation else "")
                for line, x in zip(prompt.cloze, prompt.examples)
            )
            heading = "Which word is missing?"
            controls = (f"{hidden}<input type='text' name='answer' autofocus "
                        "autocomplete='off' spellcheck='false'>"
                        "<button class='go' type='submit'>Check</button>"
                        "<button name='action' value='skip'>Skip</button>")
        else:
            shown = "".join(
                f"<p class='en'>{escape(x.translation or x.text)}</p>"
                for x in prompt.examples
            ) or "<p class='empty'>No example sentences for this one.</p>"
            heading = f"Say this using {escape(unit.key)}"
            if revealed:
                shown += "<h2>How it is actually said</h2>" + "".join(
                    f"<p class='de'>{escape(x.text)}</p>" for x in prompt.examples
                )
                controls = (f"{hidden}"
                            "<button class='go' name='action' value='yes'>Got it</button>"
                            "<button name='action' value='no'>Missed it</button>")
            else:
                controls = (f"{hidden}"
                            "<input type='hidden' name='action' value='reveal'>"
                            "<button class='go' type='submit'>Show me</button>"
                            "<button name='action' value='skip'>Skip</button>")
        return (
            f"<h1>{heading}</h1>"
            f"<p class='note'>{due:,} card{'s' if due != 1 else ''} due.</p>"
            f"<div class='prompt'>{shown}</div>"
            f"<form class='answer' method='post' action='/review'>{controls}</form>"
        )

    # --- bits -------------------------------------------------------------

    def _next_step(self, steps):
        """The earliest step still waiting to be learned, or None if none is.

        A step's card is created due, so before any review this is step one;
        answering it schedules the card forward and the next step surfaces.
        Ordering by roadmap position rather than by due date matters — the
        roadmap is a sequence, and the point is to meet it in order.
        """
        waiting = {c.unit for c in
                   self._app.card_store.due(datetime.now(), limit=100_000)}
        return next((s for s in steps if s.unit in waiting), None)

    @staticmethod
    def _filters(needle: str, kind: str, source: str) -> str:
        options = "".join(
            f"<option value='{v}'{' selected' if kind == v else ''}>{label}</option>"
            for v, label in (("", "words and patterns"), ("word", "words only"),
                             ("pattern", "patterns only"))
        )
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


def _blank(line: str) -> str:
    return escape(line.strip()).replace("_____", "<span class='blank'></span>")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip()).lower()
