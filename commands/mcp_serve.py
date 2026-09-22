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
    "on. A word marked known is a claim on probation: `due_cards` are the "
    "claims to test today, each with what to ask; `grade` records the "
    "answer — five passes graduate a word, two failures in a row un-mark "
    "it. `due_sentences` and `grade_sentence` do the same for the sentences "
    "the learner wrote to say. `check_word` explains why a word on the study "
    "list is or is not being taught. `status` says what is built; the "
    "`roadmap://` resource is a whole stored plan."
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
        """The claims to test now, soonest first, each with what to ask.

        You are the examiner. Ask the learner to write a German sentence
        using `spoken` (the word, or the verb of a pattern); do not show
        `examples` — sentences they have not seen, with English — until
        they have answered, then use them to show how it is used. Pass if
        the sentence uses the word correctly in the sense of the examples
        (any correct form of it; slips elsewhere in the sentence do not
        fail it, but point them out and give the natural phrasing). Then
        call `grade` with the verdict. `confirmations` is passes in a row
        so far (five graduate the word), `lapses` failures in a row (two
        un-mark it). `due_because` is "date" or "heard": the word became
        familiar watching -- `heard_level` climbs to five on hearings
        spaced days apart, which calls the test early, once; `heard` is
        every time it was met, and `heard_in` lines they actually heard it
        in, good to ask about.
        """
        out = []
        for card, why in self.app.due_cards(datetime.now(), limit):
            out.append({**_card(card), **self.prompt_for(card.unit),
                        # Its date, or the top of the hearing ladder since
                        # the last review -- passive hearing calls the test.
                        "due_because": why,
                        "heard": self.app.encounters.count(card.unit),
                        "heard_level": self.app.encounters.rung(card.unit).level,
                        "heard_in": [l["text"] for l in self.app.encounters.lines(card.unit, 3)],
                        # What they wrote with it before, newest first: the
                        # note is what they keep getting wrong.
                        "attempts": self.app.attempts.of(card.unit)})
        return out

    def prompt_for(self, unit: Unit) -> dict[str, Any]:
        """What to ask about one unit: the word to write with, and fresh
        sentences that show how it is used.

        Fresh: not the sentences the plan taught the word with, which the
        learner would recognise as sentences rather than know as the word.
        Subtitle and generated text only, never a transcript's, which does
        not leave the machine.
        """
        from deck.spoken import spoken                       # noqa: PLC0415
        from roadmap.examples import ExampleIndex            # noqa: PLC0415
        known = self.viewer.known
        seen = self._taught_with(unit)
        holding = self.app.corpus("subtitle", "generated", strict=True,
                                  holding=(unit.kind, unit.key))
        ranked = ExampleIndex(holding).examples(
            unit, known, limit=12, verdicts=self.app.verdicts(), judged=self.app.judged)
        fresh = [s for s in ranked if s.text not in seen] or ranked
        fresh = self.app.with_english(fresh[:3])
        return {"task": "write", "spoken": spoken(unit.key),
                "meaning": self.app.glosses.sense(unit.kind, unit.key, fresh[0].text,
                                                  self.app.llm_model) if fresh else None,
                "examples": [{"text": s.text, "english": s.translation or "",
                              "surface": s.surface_of(unit)} for s in fresh]}

    def _taught_with(self, unit: Unit) -> set[str]:
        """The sentences every stored plan showed for the unit."""
        from state import open_state                         # noqa: PLC0415
        with open_state(self.app.settings.state_path) as conn:
            return {t for (t,) in conn.execute(
                "SELECT sentence FROM roadmap WHERE kind = ? AND key = ?"
                " UNION SELECT e.text FROM roadmap_example e"
                " JOIN roadmap r ON r.source = e.source AND r.position = e.position"
                " WHERE r.kind = ? AND r.key = ? AND e.n < 3",
                (unit.kind, unit.key, unit.kind, unit.key))}

    def due_sentences(self, limit: int = 20) -> list[dict[str, Any]]:
        """The learner's own sentences to ask for now (see `/mine`): show
        `english` and ask for the German; `text` is their sentence, do not
        show it until they have answered. Pass if they said it, or said it
        with a slip you would let go in conversation; then `grade_sentence`."""
        return self.app.own.due(datetime.now())[:limit]

    def grade_sentence(self, text: str, correct: bool) -> dict[str, Any]:
        """Grade one of the learner's own sentences, `text` as `due_sentences`
        gave it, and reschedule it."""
        self.app.own.grade(text, correct, datetime.now())
        return {"text": text, "correct": correct}

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

    def grade(self, key: str, correct: bool, kind: str = LEMMA, written: str = "",
              note: str = "", german: str = "") -> dict[str, Any]:
        """Grade a review of one claim and say what became of it. Pass what
        the learner wrote as `written`, your one-line note as `note` and
        the natural phrasing as `german`; they are kept as the word's
        history and shown at the next review. `outcome` is `scheduled`
        (asked again at `due`), `graduated` (five passes: the word is known
        for good, no more reviews) or `unmarked` (two failures in a row:
        the word is no longer counted as known and the plan will teach it
        again). Tell the learner which."""
        from srs.scheduler import GRADUATED, UNMARKED, verdict  # noqa: PLC0415
        unit = _parse(kind, key)
        card = self.app.card_store.get(unit)
        if card is None:
            raise ValueError(f"no card for {unit}; `due_cards` lists the ones "
                             "there are")
        if written:
            self.app.attempts.add(unit, written, german or None, note or None, None,
                                  correct, "claude")
        reviewed = self.app.scheduler.review(card, correct, datetime.now())
        outcome = verdict(reviewed)
        if outcome == GRADUATED:
            self.app.card_store.remove(unit)
        elif outcome == UNMARKED:
            self.viewer.mark_known({"kind": unit.kind, "key": unit.key, "action": "undo"})
        else:
            self.app.card_store.save(reviewed)
        return {**_card(reviewed), "outcome": outcome}

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
        "confirmations": card.repetitions,
        "lapses": card.lapses,
        "last_review": (card.last_review.isoformat(timespec="seconds")
                        if card.last_review else None),
    }


def examiner() -> str:
    """Run a review session: test each claim due today, grade it, repeat."""
    return (
        "You are my German examiner, working from my own review queue through "
        "this server. Call `due_cards`. For each card, ask me to write a "
        "sentence using the word. Wait for my answer. Judge it as the tool "
        "describes — strict on the word, lenient elsewhere — tell me in a line "
        "what was right or wrong and the natural phrasing, show one of the "
        "examples, and call `grade` with my sentence, your note and the "
        "phrasing, so the next review can see them. Read `attempts` first: "
        "if I made the same mistake before, say so. "
        "Tell me when a word graduates or is un-marked. Then `due_sentences`: "
        "show me the English of each and ask for my German; `grade_sentence`. "
        "End with what passed, what did not, and what is gone back to the plan."
    )


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
    server.tool(annotations=reads)(tools.due_sentences)
    server.tool()(anticipated(tools.mark_known))
    server.tool()(anticipated(tools.grade))
    server.tool()(tools.grade_sentence)
    server.resource("roadmap://{label}", mime_type="text/plain")(tools.roadmap)
    server.prompt()(tutor)
    server.prompt()(examiner)
    return server


class McpServeCommand:
    """Serves until the client closes stdin."""

    def run(self, app) -> None:
        build(Tools(app)).run()
