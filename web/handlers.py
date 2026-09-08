"""What each page shows.

One method per route. Handlers return finished HTML; the server does the
sockets and nothing else.
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from datetime import datetime
from html import escape

from roadmap import ExampleIndex, RoadmapStore
from srs import PromptBuilder, SM2Scheduler
from vocab.entry import Unit
from web.render import layout, sentence_block, stat, tag

PAGE_SIZE = 50


class Viewer:
    """Reads the built results and renders them.

    The corpus and known set load once, on first use, because both cost
    seconds and every page after the first wants them.
    """

    def __init__(self, app) -> None:
        self._app = app
        self._corpus = None
        self._known = None
        self._examples = None
        self._scheduler = SM2Scheduler()

    # --- lazily loaded state ---------------------------------------------

    @property
    def corpus(self):
        if self._corpus is None:
            self._corpus = self._app.corpus()
        return self._corpus

    @property
    def known(self) -> frozenset[Unit]:
        if self._known is None:
            self._known = self._app.known_set().units
        return self._known

    @property
    def examples(self) -> ExampleIndex:
        if self._examples is None:
            self._examples = ExampleIndex(self.corpus)
        return self._examples

    @property
    def steps(self):
        return RoadmapStore(self._app.settings.state_path).load()

    # --- pages ------------------------------------------------------------

    def overview(self, query: dict) -> str:
        builds = self._app.corpus_store.builds()
        total, due = self._app.card_store.counts(datetime.now())
        steps = RoadmapStore(self._app.settings.state_path).count()

        tiles = "".join([
            stat(f"{sum(builds.values()):,}", "sentences cached"),
            stat(f"{steps:,}", "roadmap steps"),
            stat(f"{due:,}", "cards due now"),
            stat(f"{total:,}", "cards scheduled"),
        ])
        rows = "".join(
            f"<tr><td><code>{escape(name)}</code></td>"
            f"<td class='num'>{count:,}</td></tr>"
            for name, count in sorted(builds.items())
        )
        body = (
            "<h1>Overview</h1>"
            "<p class='sub'>What has been built, and what is waiting.</p>"
            f"<div class='cards'>{tiles}</div>"
            "<h2>Corpus builds</h2>"
            f"<table><tr><th>build</th><th class='num'>sentences</th></tr>{rows}</table>"
            "<h2>Next</h2>"
            f"<p class='sub'><a href='/roadmap'>Browse the roadmap</a> · "
            f"<a href='/review'>Review {due} due card" + ("s" if due != 1 else "") + "</a></p>"
        )
        return layout("Overview", body, "/")

    def roadmap(self, query: dict) -> str:
        steps = self.steps
        needle = (query.get("q") or "").strip().lower()
        kind = query.get("kind") or ""
        if needle:
            steps = [s for s in steps
                     if needle in s.unit.key.lower()
                     or needle in s.sentence.text.lower()]
        if kind in ("word", "pattern"):
            steps = [s for s in steps if s.unit.is_pattern == (kind == "pattern")]

        page = max(int(query.get("page") or 1), 1)
        pages = max((len(steps) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        window = steps[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

        rows = "".join(
            f"<div class='row'><div class='pos'>{s.position}</div>"
            f"<div class='body'>"
            f"<a class='unit' href='/unit/{s.unit.kind}/{_quote(s.unit.key)}'>"
            f"{escape(s.unit.key)}</a>"
            f"{sentence_block(s.sentence.text, s.sentence.translation)}</div>"
            f"{tag(s.unit.kind)}</div>"
            for s in window
        ) or "<p class='empty'>Nothing matches.</p>"

        body = (
            "<h1>Roadmap</h1>"
            f"<p class='sub'>{len(steps):,} steps, in the order they are taught. "
            "Each one is the single unknown in its sentence.</p>"
            f"{self._filters(needle, kind)}"
            f"{rows}"
            f"{self._pager(page, pages, needle, kind)}"
        )
        return layout("Roadmap", body, "/roadmap")

    def unit(self, kind: str, key: str, query: dict) -> str:
        target = Unit(kind, key)
        found = self.examples.examples(target, self.known, limit=25)
        blocks = "".join(
            f"<div class='row'><div class='body'>"
            f"{sentence_block(s.text, s.translation)}</div>"
            f"<span class='tag'>{len(s.units - self.known - {target})} unknown</span></div>"
            for s in found
        ) or "<p class='empty'>No sentence in the corpus uses this.</p>"

        position = next((s.position for s in self.steps if s.unit == target), None)
        where = f"step {position} of the roadmap" if position else "not in the roadmap"
        body = (
            f"<h1>{escape(key)}</h1>"
            f"<p class='sub'>{tag(kind)} &nbsp; {escape(where)} &nbsp; · &nbsp; "
            f"{self.examples.count(target):,} sentences in the corpus use it</p>"
            f"<h2>Examples, most readable first</h2>{blocks}"
        )
        return layout(key, body, "/roadmap")

    def subtitles(self, query: dict) -> str:
        by_video: dict[str, list] = defaultdict(list)
        for sentence in self._app.corpus_store.load("subtitle", "subtitle:llm",
                                                    teachable_only=False):
            if sentence.timing:
                by_video[sentence.timing.video_id].append(sentence)

        rows = "".join(
            f"<tr><td><code>{escape(video)}</code></td>"
            f"<td class='num'>{len(group):,}</td>"
            f"<td class='num'>{max(s.timing.end for s in group) / 60:.1f} min</td></tr>"
            for video, group in sorted(by_video.items())
        ) or "<tr><td colspan='3' class='empty'>No aligned subtitles yet.</td></tr>"

        body = (
            "<h1>Subtitles</h1>"
            "<p class='sub'>Corrected subtitles aligned back to the video clock. "
            "Export them with "
            "<code>python main.py export-subtitles</code>.</p>"
            f"<table><tr><th>video</th><th class='num'>cues</th>"
            f"<th class='num'>length</th></tr>{rows}</table>"
        )
        return layout("Subtitles", body, "/subtitles")

    # --- review -----------------------------------------------------------

    def review(self, query: dict, verdict: str = "") -> str:
        now = datetime.now()
        total, due = self._app.card_store.counts(now)
        cards = self._app.card_store.due(now, limit=1)
        if not cards:
            body = (verdict + "<h1>Review</h1>"
                    f"<p class='empty'>Nothing due. {total:,} cards scheduled.</p>")
            return layout("Review", body, "/review")

        prompt = PromptBuilder(self.examples, self._app.settings.examples_per_card
                               ).build(cards[0], self.known)
        reveal = query.get("reveal") == "1"
        body = verdict + self._card_form(prompt, due, total, reveal)
        return layout("Review", body, "/review")

    def grade(self, form: dict) -> str:
        """Apply an answer, then show the next card with the verdict."""
        unit = Unit(form.get("kind", ""), form.get("key", ""))
        card = next((c for c in self._app.card_store.due(datetime.now(), limit=200)
                     if c.unit == unit), None)
        if card is None:
            return self.review({})

        if form.get("action") == "reveal":
            prompt = PromptBuilder(self.examples,
                                   self._app.settings.examples_per_card
                                   ).build(card, self.known)
            _, due = self._app.card_store.counts(datetime.now())
            return layout("Review",
                          self._card_form(prompt, due, due, revealed=True), "/review")

        if form.get("action") == "skip":
            return self.review({})

        if form.get("action") in ("yes", "no"):
            correct = form["action"] == "yes"
            shown = escape(unit.key)
        else:
            answer = form.get("answer", "")
            correct = _fold(answer) == _fold(unit.key)
            shown = escape(unit.key)

        self._app.card_store.save(
            self._scheduler.review(card, correct, datetime.now())
        )
        css, word = ("ok", "Correct") if correct else ("no", "Missed")
        verdict = f"<div class='verdict {css}'><strong>{word}</strong> — {shown}</div>"
        return self.review({}, verdict)

    def _card_form(self, prompt, due: int, total: int, revealed: bool = False) -> str:
        unit = prompt.unit
        hidden = (f"<input type='hidden' name='kind' value='{escape(unit.kind)}'>"
                  f"<input type='hidden' name='key' value='{escape(unit.key)}'>")
        lines = "".join(
            f"<div class='cloze'>{_cloze(line)}</div>" if prompt.cloze
            else f"<div class='de'>{escape(line.strip(' •'))}</div>"
            for line in prompt.question_lines()
        )
        if prompt.self_graded and not revealed:
            controls = (f"{hidden}<input type='hidden' name='action' value='reveal'>"
                        "<button class='primary' type='submit'>Reveal</button>")
        elif prompt.self_graded:
            answers = "".join(f"<div class='de'>{escape(x.strip())}</div>"
                              for x in prompt.answer_lines())
            lines += f"<h2>How it is actually said</h2>{answers}"
            controls = (f"{hidden}"
                        "<button class='primary' name='action' value='yes'>Got it</button>"
                        "<button name='action' value='no'>Missed</button>")
        else:
            controls = (f"{hidden}<input type='text' name='answer' autofocus "
                        "autocomplete='off' placeholder='the missing word'>"
                        "<button class='primary' type='submit'>Check</button>"
                        "<button name='action' value='skip'>Skip</button>")
        return (
            "<h1>Review</h1>"
            f"<p class='sub'>{due:,} due &nbsp;·&nbsp; {tag(unit.kind)} "
            f"{escape(prompt.heading)}</p>"
            f"{lines}"
            f"<form class='inline' method='post' action='/review'>{controls}</form>"
        )

    # --- bits -------------------------------------------------------------

    @staticmethod
    def _filters(needle: str, kind: str) -> str:
        options = "".join(
            f"<option value='{v}'{' selected' if kind == v else ''}>{label}</option>"
            for v, label in (("", "everything"), ("word", "words only"),
                             ("pattern", "patterns only"))
        )
        return ("<form class='inline' method='get' action='/roadmap'>"
                f"<input type='text' name='q' value='{escape(needle)}' "
                "placeholder='search a word, a pattern or a sentence'>"
                f"<select name='kind' style='padding:9px'>{options}</select>"
                "<button type='submit'>Filter</button></form>")

    @staticmethod
    def _pager(page: int, pages: int, needle: str, kind: str) -> str:
        extra = f"&q={_quote(needle)}&kind={_quote(kind)}"
        back = (f"<a href='/roadmap?page={page - 1}{extra}'>← previous</a>"
                if page > 1 else "")
        forward = (f"<a href='/roadmap?page={page + 1}{extra}'>next →</a>"
                   if page < pages else "")
        return f"<div class='pager'>{back}<span>page {page} of {pages}</span>{forward}</div>"


def _cloze(line: str) -> str:
    return escape(line.strip()).replace("_____", "<span class='blank'></span>")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip()).lower()


def _quote(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")
