"""The review session, as a page.

Kept beside the other pages rather than inside them: reviewing is the only
part of the viewer that writes, and its two-step reveal for pattern cards is
enough logic to be worth its own seam.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime
from html import escape

from srs import PromptBuilder, SM2Scheduler
from vocab.entry import Unit
from web.render import layout


class ReviewSection:
    """Renders and grades the card that is due."""

    def __init__(self, viewer) -> None:
        self._viewer = viewer
        self._app = viewer.app
        self._scheduler = SM2Scheduler()

    def page(self, query: dict, verdict: str = "") -> str:
        source = self._viewer.source(query)
        now = datetime.now()
        total, due = self._app.card_store.counts(now)
        cards = self._app.card_store.due(now, limit=1)
        switch = self._viewer.switch(source, "/review")
        if not cards:
            body = (switch + verdict + "<h1>Nothing due</h1>"
                    f"<p class='empty'>{total:,} cards are scheduled. Come back "
                    "when one comes round, or learn something new from "
                    "<a href='/'>what is next</a>.</p>")
            return layout("Review", body, "/review", source)
        prompt = self._prompt(cards[0], source)
        return layout("Review", switch + verdict + self._card(prompt, due, source),
                      "/review", source)

    def grade(self, form: dict) -> str:
        source = form.get("src") or ""
        unit = Unit(form.get("kind", ""), form.get("key", ""))
        card = next((c for c in self._app.card_store.due(datetime.now(), limit=400)
                     if c.unit == unit), None)
        if card is None:
            return self.page({"src": source})

        action = form.get("action", "")
        if action == "skip":
            return self.page({"src": source})
        if action == "reveal":
            _, due = self._app.card_store.counts(datetime.now())
            return layout(
                "Review",
                self._viewer.switch(source, "/review") +
                self._card(self._prompt(card, source), due, source, revealed=True),
                "/review", source,
            )

        correct = (action == "yes" if action in ("yes", "no")
                   else _fold(form.get("answer", "")) == _fold(unit.key))
        self._app.card_store.save(
            self._scheduler.review(card, correct, datetime.now())
        )
        word = "Right." if correct else "Not this time."
        verdict = (f"<p class='mark {'right' if correct else ''}'>{word} "
                   f"<span class='target'>{escape(unit.key)}</span></p>")
        return self.page({"src": source}, verdict)

    def _prompt(self, card, source: str):
        return PromptBuilder(self._viewer.scope(source).examples,
                             self._app.settings.examples_per_card
                             ).build(card, self._viewer.known)

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
                controls = (f"{hidden}<input type='hidden' name='action' value='reveal'>"
                            "<button class='go' type='submit'>Show me</button>"
                            "<button name='action' value='skip'>Skip</button>")
        return (f"<h1>{heading}</h1>"
                f"<p class='note'>{due:,} card{'s' if due != 1 else ''} due.</p>"
                f"<div class='prompt'>{shown}</div>"
                f"<form class='answer' method='post' action='/review'>{controls}</form>")


def _blank(line: str) -> str:
    return escape(line.strip()).replace("_____", "<span class='blank'></span>")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip()).lower()
