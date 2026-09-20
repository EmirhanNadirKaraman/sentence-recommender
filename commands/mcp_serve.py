"""`mcp-serve` — the project as tools for an MCP client, over stdio.

MCP is how an agent — Claude Code, Claude Desktop, anything that speaks
it — discovers and calls what a program can do. The server publishes each
tool's name, description and input schema; the client reads them when it
connects and decides for itself when to call what. So a tutor session in
Claude becomes: ask for the next step, show the sentence, mark the word,
ask again — against this reader's own roadmap and review queue, with no
integration written on the other side.

A subcommand rather than a script beside the app, because `main()` already
resolves the settings and the goal list, and `Application` already holds
everything the tools answer from. The server is one more reader of it, like
the web viewer — and it shares `Viewer`, so "the next step" here is the same
step the page would show, decided by the same stored plan.

stdio, because that is how a local server is launched: the client spawns
this process and speaks JSON-RPC over its stdin and stdout. The SDK moves
the wire onto a private descriptor and points the process's stdout at
stderr while it serves, so the commands wrapped here can go on printing
without corrupting the framing. What they print is captured where it *is*
the answer — `check` and `status` say what they found rather than return
it — and lands on stderr otherwise.

The tool logic lives on `Tools` as plain methods and the SDK is imported
only in `build`, so the tests can call the methods without a client and the
rest of the suite can import this package without the `mcp` package.
"""
from __future__ import annotations

import functools
import io
from contextlib import redirect_stdout
from datetime import datetime
from threading import Lock
from typing import Any

from commands.check_word import CheckWordCommand
from commands.status import StatusCommand
from roadmap import RoadmapStore
from roadmap.store import current_stamp
from srs.card import Card
from vocab.entry import LEMMA, PATTERN, Unit
from web.handlers import Viewer

NAME = "sentence-recommender"

INSTRUCTIONS = (
    "A German learner's own i+1 roadmap and spaced-repetition queue. "
    "`next_up` is the sentence to teach now — everything in it is known "
    "except one unit. `mark_known` records the decision and moves the plan "
    "on. `due_cards` and `grade` run reviews. `check_word` explains why a "
    "word on the study list is or is not being taught. `status` says what is "
    "built; the `roadmap://` resource is a whole stored plan."
)

ACTIONS = ("known", "pass", "undo")


class Tools:
    """What the server offers, as methods that return plain data.

    Kept apart from the SDK so a test can call `next_up()` and read a dict,
    rather than drive a client to get at the same dict wrapped in a result.
    """

    def __init__(self, app) -> None:
        self.app = app
        self.viewer = Viewer(app)
        self._roadmaps = RoadmapStore(app.settings.state_path)
        # `redirect_stdout` swaps the process-wide stream, and the SDK runs
        # tools on worker threads: two captures at once would read each
        # other's output. One at a time.
        self._capturing = Lock()

    # --- reading ----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """What is built and what is due: corpus builds with their sentence
        counts, stored roadmaps with their step counts (the names the
        `roadmap://` resource takes), scheduled and due cards, and whether
        the vocabulary files are present."""
        return StatusCommand().gather(self.app)

    def check_word(self, word: str) -> str:
        """Trace one word from the study list to the corpus and say why it
        is or is not taught: whether the list and the dictionary have it,
        which lemma the parser gives it, and where the corpus says it. The
        answer to "this word is on my list and the roadmap never teaches
        it"."""
        return self._captured(CheckWordCommand(), word)

    def next_up(self, source: str = "", only: str = "",
                counting: str = "all") -> dict[str, Any]:
        """The next i+1 step: a sentence in which every unit is known except
        one, the unit it teaches, and a deck of further sentences that say
        it. `readable` of `total` is how far the reader is. `empty` means
        nothing left is one unit away.

        `source` names a corpus build (`subtitle`, `tatoeba`, `all`); empty
        takes the default. `only="word"` skips the pattern steps. `counting`
        is `all` to count every word, `list` to count only the study list,
        `unblock` to let the plan teach a word off the list when it is in
        the way. Where a roadmap has been built for the source the answer
        is a query; where none has, it is a walk over the corpus, which
        takes seconds on a subtitle build and longer on a large one.
        """
        query = {"src": source, "only": only, "count": counting}
        source = self.viewer.source(query)
        step, deck, readable, occurrences, total = self.viewer.next_step(
            query, source, only)
        if step is None:
            return {"empty": True, "source": source,
                    "readable": readable, "total": total}
        return {
            "source": source,
            "unit": _unit(step.unit),
            "beside": _unit(step.beside) if step.beside else None,
            "sentence": _sentence(step.sentence, step.unit),
            "examples": [_sentence(s, step.unit) for s in deck],
            "readable": readable,
            "total": total,
            "occurrences": occurrences,
        }

    def due_cards(self, limit: int = 20) -> list[dict[str, Any]]:
        """The review cards due now, soonest first, with their SM-2 state."""
        return [_card(c) for c in self.app.card_store.due(datetime.now(), limit)]

    def roadmap(self, label: str) -> str:
        """A stored roadmap, one step per line: position, kind, unit, the
        sentence that teaches it. `status` lists the labels."""
        steps = self._roadmaps.load(label)
        if not steps:
            return (f"no stored roadmap called {label!r}; "
                    "`status` lists the ones there are")
        lines = [f"{s.position:>5}. {s.unit.kind:<8}{s.unit.key:<32}"
                 f"{s.sentence.text}" for s in steps]
        # A plan built under earlier rules is still readable, but it is not
        # what `next_up` serves — that walks the corpus instead, as the page
        # does — and two tools on one server must not contradict each other
        # in silence.
        if self._roadmaps.stamp(label) != current_stamp():
            lines.insert(0, "(built under earlier rules than the ones in "
                            "force: `next_up` walks the corpus instead of "
                            "following this; `build-roadmap` brings it up "
                            "to date)")
        return "\n".join(lines)

    # --- deciding ---------------------------------------------------------

    def mark_known(self, key: str, kind: str = LEMMA, action: str = "known",
                   source: str = "") -> dict[str, Any]:
        """Record a decision about a unit, as the reading page does. `known`
        marks it learned — every index moves on and its review card goes.
        `pass` sets it aside for a while without learning it. `undo` takes
        back a `known`. `kind` is `lemma` or `pattern`, `key` the unit's key
        as `next_up` gave it."""
        unit = _parse(kind, key)
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}, not {action!r}")
        self.viewer.mark_known({"kind": unit.kind, "key": unit.key,
                                "action": action, "src": source})
        return {"unit": _unit(unit), "action": action}

    def grade(self, key: str, correct: bool, kind: str = LEMMA) -> dict[str, Any]:
        """Grade a review of one card and reschedule it by SM-2. Returns the
        card's new state; the next due date is what the grade decided."""
        unit = _parse(kind, key)
        card = self.app.card_store.get(unit)
        if card is None:
            raise ValueError(f"no card for {unit}; `due_cards` lists the ones "
                             "there are")
        reviewed = self.app.scheduler.review(card, correct, datetime.now())
        self.app.card_store.save(reviewed)
        return _card(reviewed)

    # --- helpers ----------------------------------------------------------

    def _captured(self, command, *args) -> str:
        """Run a command that prints its answer and return what it printed."""
        buffer = io.StringIO()
        with self._capturing, redirect_stdout(buffer):
            command.run(self.app, *args)
        return buffer.getvalue()


def _parse(kind: str, key: str) -> Unit:
    if kind not in (LEMMA, PATTERN):
        raise ValueError(f"kind must be {LEMMA!r} or {PATTERN!r}, not {kind!r}")
    if not key.strip():
        raise ValueError("key is empty")
    # The key as given, not lowercased: a unit read back from `next_up`
    # must round-trip, and `Unit.lemma` would fold `Treffen` into `treffen`.
    return Unit(kind, key.strip())


def _unit(unit: Unit) -> dict[str, str]:
    return {"kind": unit.kind, "key": unit.key}


def _sentence(sentence, unit: Unit) -> dict[str, Any]:
    out: dict[str, Any] = {
        "text": sentence.text,
        "translation": sentence.translation,
        "origin": sentence.origin,
        # The form the sentence actually uses — `hat` for `haben` — so the
        # new word can be pointed at rather than only named.
        "surface": sentence.surface_of(unit),
    }
    if sentence.timing:
        out["video"] = {"id": sentence.timing.video_id,
                        "start": sentence.timing.start,
                        "end": sentence.timing.end}
    return out


def _card(card: Card) -> dict[str, Any]:
    return {
        "unit": _unit(card.unit),
        "due": card.due_date.isoformat(timespec="seconds"),
        "interval_days": card.interval_days,
        "ease": card.ease_factor,
        "repetitions": card.repetitions,
        "last_review": (card.last_review.isoformat(timespec="seconds")
                        if card.last_review else None),
    }


def tutor() -> str:
    """Run a reading session: teach the next step, record the decision,
    repeat."""
    return (
        "You are my German tutor, working from my own roadmap through this "
        "server. Loop: call `next_up`. Show me the sentence and its "
        "translation, but do not name the new unit — ask me what it means. "
        "Then reveal it with two or three of the examples. If I say I know "
        "it, call `mark_known`; if I want it later, `mark_known` with "
        "action='pass'. Then `next_up` again. Stop when I say so, and end "
        "with the list of what I learned."
    )


def build(tools: Tools):
    """The server with everything registered, not yet running — so a test
    can connect to it in-process."""
    from mcp.server import MCPServer            # noqa: PLC0415 — `mcp-serve` only
    from mcp.server.mcpserver.exceptions import ToolError   # noqa: PLC0415
    from mcp.types import ToolAnnotations        # noqa: PLC0415

    def anticipated(method):
        # A `ValueError` out of a tool is a bad argument — the model's
        # mistake to read and correct — and the SDK only passes a message
        # through for its own `ToolError`; anything else it reports as
        # `Error executing tool <name>` and keeps the reason in the log.
        @functools.wraps(method)
        def wrapped(*args, **kwargs):
            try:
                return method(*args, **kwargs)
            except ValueError as error:
                raise ToolError(str(error)) from error
        return wrapped

    server = MCPServer(NAME, instructions=INSTRUCTIONS)
    reads = ToolAnnotations(read_only_hint=True)
    server.tool(annotations=reads)(tools.status)
    server.tool(annotations=reads)(anticipated(tools.check_word))
    server.tool(annotations=reads)(anticipated(tools.next_up))
    server.tool(annotations=reads)(tools.due_cards)
    server.tool()(anticipated(tools.mark_known))
    server.tool()(anticipated(tools.grade))
    server.resource("roadmap://{label}", mime_type="text/plain")(tools.roadmap)
    server.prompt()(tutor)
    return server


class McpServeCommand:
    """Serves until the client closes stdin."""

    def run(self, app) -> None:
        build(Tools(app)).run()
