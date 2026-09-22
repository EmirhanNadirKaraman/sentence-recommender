"""The MCP server: the tools as data, and the wire around them.

Two layers, tested apart. `Tools` is plain methods over an `Application`,
and most of what can go wrong is there: a step served twice because marking
it known changed nothing the next call reads, a `pass` that did not set the
word aside, a grade that did not move the due date. Those run against a
stub app on a temporary state file — no corpus, no database, no spaCy.

The SDK layer is one in-process client: that every tool, the resource and
the prompt are actually published, that a dict comes back as structured
content, and that a bad argument reaches the model as a readable error and
not as `Error executing tool`. The SDK is only installed in `.venv`, so
those cases are skipped rather than failed where it is missing.
"""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from context import Application
from commands.mcp_serve import Tools, tutor
from config import Settings
from corpus.sentence import Sentence
from roadmap.known_set import KnownSet
from roadmap.step import RoadmapStep
from roadmap.store import RoadmapStore, current_stamp
from srs import CardStore, SM2Scheduler
from vocab.entry import Unit
from vocab.attempts import Attempts
from vocab.encounters import Encounters
from vocab.own_sentences import OwnSentences
from vocab.known_store import KnownStore
from vocab.snooze_store import SnoozeStore

try:
    from mcp import Client
    from commands.mcp_serve import build
except ImportError:                        # pragma: no cover — system python
    Client = None

LABEL = "subtitle:strict:goals"
NOW = datetime(2026, 1, 1, 12, 0)


def sentence(text: str, unit: Unit, surface: str, *others: Unit) -> Sentence:
    return Sentence(text=text, translation=f"({text})").with_units(
        frozenset({unit, *others}), ((unit, surface),))


def step(position: int, key: str, text: str, surface: str) -> RoadmapStep:
    unit = Unit.lemma(key)
    taught = sentence(text, unit, surface)
    return RoadmapStep(position=position, unit=unit, sentence=taught,
                       gain=1, score=1.0, now_readable=1,
                       examples=(taught,), readable=position, occurrences=2)


STEPS = [
    step(1, "merken", "Merk dir das.", "Merk"),
    step(2, "anders", "Das ist anders.", "anders"),
    step(3, "sogar", "Sogar du.", "Sogar"),
]


def stub_app(tmp: Path) -> SimpleNamespace:
    """Enough of an `Application` for the server: the stores it writes,
    on a state file of their own, and the two corpus questions stubbed."""
    state = tmp / "state.sqlite3"
    settings = SimpleNamespace(
        state_path=state,
        # The same stem as the default list, so the plan's label carries no
        # list name and `LABEL` above is the one the viewer looks for.
        goal_words=Settings().goal_words,
        known_words=tmp / "known.txt", function_words=tmp / "function.txt",
        snooze_words=20,
    )
    app = SimpleNamespace(
        settings=settings,
        card_store=CardStore(state),
        scheduler=SM2Scheduler(),
        snoozes=SnoozeStore(state),
        marked_known=KnownStore(state),
        corpus_store=SimpleNamespace(
            builds=lambda teachable_only=False: {"subtitle": 3}),
        apply_overrides=lambda deck, resolve=None: deck,
        # What a review prompt reads: the sentences saying a word (none
        # here), the verdicts and the judge, the English, and Mine.
        corpus=lambda *builds, **query: [],
        verdicts=lambda: {},
        judged=None,
        with_english=lambda sentences: sentences,
        glosses=SimpleNamespace(sense=lambda *a, **k: None),
        llm_model="",
        own=OwnSentences(state),
        attempts=Attempts(state),
        encounters=Encounters(state),
    )
    app.known_set = lambda: KnownSet(app.marked_known.units())
    app.due_cards = lambda now=None, limit=20: Application.due_cards(app, now, limit)
    RoadmapStore(state).save(STEPS, LABEL, stamp=current_stamp(), total=3)
    return app


class ToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.app = stub_app(Path(self._tmp.name))
        self.tools = Tools(self.app)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_status_is_data(self) -> None:
        report = self.tools.status()
        self.assertEqual(report["corpus"], {"subtitle": 3})
        self.assertEqual(report["roadmaps"], {LABEL: 3})
        self.assertEqual(report["cards"], {"scheduled": 0, "due": 0})
        self.assertEqual(report["vocab"],
                         {"known.txt": False, "function.txt": False})

    def test_next_up_is_the_first_stored_step(self) -> None:
        got = self.tools.next_up(source="subtitle")
        self.assertEqual(got["unit"], {"kind": "lemma", "key": "merken"})
        self.assertEqual(got["sentence"]["text"], "Merk dir das.")
        self.assertEqual(got["sentence"]["surface"], "Merk")
        self.assertEqual(got["sentence"]["translation"], "(Merk dir das.)")
        self.assertEqual([e["text"] for e in got["examples"]],
                         ["Merk dir das."])
        self.assertEqual((got["readable"], got["total"]), (1, 3))
        self.assertIsNone(got["beside"])

    def test_a_word_met_watching_comes_first(self) -> None:
        """Of the next few steps, the one heard on the most spaced days is
        offered before the plan's own first -- when a sentence of its deck
        needs only it. Heard the same, the plan's order holds."""
        store = self.app.encounters
        store.add([(Unit.lemma("sogar"), "Sogar du.", "vid", 1.0)], NOW)
        self.assertEqual(self.tools.next_up("subtitle")["unit"]["key"], "sogar")
        store.add([(Unit.lemma("anders"), "Das ist anders.", "vid", 2.0)], NOW)
        self.assertEqual(self.tools.next_up("subtitle")["unit"]["key"], "anders")
        store.add([(Unit.lemma("sogar"), "Sogar sie.", "vid", 9.0)], NOW + timedelta(days=1))
        self.assertEqual(self.tools.next_up("subtitle")["unit"]["key"], "sogar")
        # Its deck no longer readable -- another word in it unknown -- the
        # heard word waits, and the plan's first is offered.
        harder = sentence("Sogar du.", Unit.lemma("sogar"), "Sogar", Unit.lemma("du"))
        RoadmapStore(self.app.settings.state_path).save(
            [STEPS[0], STEPS[1], replace(STEPS[2], sentence=harder, examples=(harder,))],
            LABEL, stamp=current_stamp(), total=3)
        self.assertEqual(self.tools.next_up("subtitle")["unit"]["key"], "anders")

    def test_marking_known_moves_the_plan_on(self) -> None:
        """The sequence, not the calls: a long-lived server that kept
        serving the word just learned would pass every single-call test."""
        self.assertEqual(self.tools.next_up("subtitle")["unit"]["key"], "merken")
        self.tools.mark_known("merken")
        self.assertEqual(self.tools.next_up("subtitle")["unit"]["key"], "anders")
        self.assertIn(Unit.lemma("merken"), self.app.marked_known.units())

    def test_pass_sets_a_word_aside_without_learning_it(self) -> None:
        self.tools.mark_known("merken", action="pass")
        self.assertEqual(self.tools.next_up("subtitle")["unit"]["key"], "anders")
        self.assertNotIn(Unit.lemma("merken"), self.app.marked_known.units())

    def test_undo_takes_a_word_back(self) -> None:
        self.tools.mark_known("merken")
        self.tools.mark_known("merken", action="undo")
        self.assertNotIn(Unit.lemma("merken"), self.app.marked_known.units())

    def test_nothing_left_says_so_with_the_counts(self) -> None:
        # A plan that has run out falls back to the live walk, as the page
        # does, and that needs the corpus. What is checked here is the
        # answer's shape once the walk has nothing either.
        self.tools.viewer.next_step = lambda query, source, only: (None, [], 5, 0, 9)
        got = self.tools.next_up("subtitle")
        self.assertEqual(got, {"empty": True, "source": "subtitle",
                               "readable": 5, "total": 9})

    def test_bad_arguments_are_refused_by_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "kind"):
            self.tools.mark_known("merken", kind="verb")
        with self.assertRaisesRegex(ValueError, "action"):
            self.tools.mark_known("merken", action="learnt")
        with self.assertRaisesRegex(ValueError, "empty"):
            self.tools.mark_known("  ")
        with self.assertRaisesRegex(ValueError, "no card"):
            self.tools.grade("merken", correct=True)

    def test_grading_reschedules_the_card(self) -> None:
        store = self.app.card_store
        store.add(self.app.scheduler.new_card(Unit.lemma("merken"), NOW))
        self.assertEqual([c["unit"]["key"] for c in self.tools.due_cards()],
                         ["merken"])
        before = datetime.now()
        got = self.tools.grade("merken", correct=True)
        self.assertEqual(got["repetitions"], 1)
        self.assertGreater(datetime.fromisoformat(got["due"]),
                           before + timedelta(days=2))
        self.assertEqual(self.tools.due_cards(), [])
        self.assertEqual(store.get(Unit.lemma("merken")).repetitions, 1)

    def test_a_familiar_word_calls_the_test_before_its_date(self) -> None:
        """Heard on five spaced days since the last review, the claim is
        due now with the reason, the level and the lines it was heard in;
        once graded, hearing it more says nothing new."""
        from srs.card import Card                        # noqa: PLC0415
        from vocab.encounters import LADDER              # noqa: PLC0415
        store = self.app.card_store
        now = datetime.now()
        # Confirmed once, 26 days ago, and not due for ten more.
        store.add(Card(Unit.lemma("merken"), now + timedelta(days=10), 40.0, 2.55, 1,
                       now - timedelta(days=26)))
        self.assertEqual(self.tools.due_cards(), [])
        day = now - timedelta(days=sum(LADDER) + 1)
        for days in LADDER:
            day += timedelta(days=days)
            # A sentence of its own each time: the same one is the same
            # hearing, however long has passed.
            self.app.encounters.add(
                [(Unit.lemma("merken"), f"Merk dir das ({days}).", "vid", 3.0)], day)
        (card,) = self.tools.due_cards()
        self.assertEqual((card["unit"]["key"], card["due_because"], card["heard_level"],
                          card["heard"], card["heard_in"][:1]),
                         ("merken", "heard", 5, 5, ["Merk dir das (16.575)."]))
        self.tools.grade("merken", correct=True)
        self.app.encounters.add([(Unit.lemma("merken"), "Merk dir das.", "vid", 3.0)])
        self.assertEqual(self.tools.due_cards(), [])

    def test_marking_known_makes_the_claim_a_card_due_tomorrow(self) -> None:
        """A word marked known is a claim on probation: known at once, and
        a card to confirm it from tomorrow. Taking the mark back withdraws
        the card with it."""
        self.tools.mark_known("merken")
        card = self.app.card_store.get(Unit.lemma("merken"))
        self.assertIsNotNone(card)
        self.assertGreater(card.due_date, datetime.now() + timedelta(hours=23))
        self.tools.mark_known("merken", action="undo")
        self.assertIsNone(self.app.card_store.get(Unit.lemma("merken")))

    def test_the_roadmap_resource_is_one_line_a_step(self) -> None:
        lines = self.tools.roadmap(LABEL).splitlines()
        self.assertEqual(len(lines), 3)
        self.assertRegex(lines[0], r"^\s+1\. lemma\s+merken\s+Merk dir das\.$")
        self.assertIn("no stored roadmap", self.tools.roadmap("nope"))

    def test_a_stale_plan_says_it_is_not_what_next_up_follows(self) -> None:
        # The stored plans on a real machine outlive the rules that built
        # them, and `next_up` then walks the corpus. The resource still
        # reads — but must say so, or the two contradict each other.
        RoadmapStore(self.app.settings.state_path).save(
            STEPS, LABEL, stamp="older|rules", total=3)
        lines = self.tools.roadmap(LABEL).splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("earlier rules", lines[0])
        self.assertIn("next_up", lines[0])

    def test_a_printing_command_is_returned_not_printed(self) -> None:
        class Says:
            def run(self, app, word):
                print(f"about {word}")

        outside = io.StringIO()
        with redirect_stdout(outside):
            got = self.tools._captured(Says(), "merken")
        self.assertEqual(got, "about merken\n")
        self.assertEqual(outside.getvalue(), "")

    def test_the_tutor_prompt_names_the_tools_it_needs(self) -> None:
        for name in ("next_up", "mark_known"):
            self.assertIn(f"`{name}`", tutor())


@unittest.skipIf(Client is None, "the mcp package is only in .venv")
class WireTest(unittest.IsolatedAsyncioTestCase):
    """The SDK layer, over an in-process client."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.server = build(Tools(stub_app(Path(self._tmp.name))))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_everything_is_published(self) -> None:
        async with Client(self.server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            self.assertEqual(
                set(tools),
                {"status", "check_word", "next_up", "due_cards", "due_sentences",
                 "mark_known", "grade", "grade_sentence"})
            # The schema comes from the signature, through the error wrapper.
            self.assertEqual(tools["grade"].input_schema["required"],
                             ["key", "correct"])
            self.assertTrue(tools["next_up"].annotations.read_only_hint)
            self.assertIsNone(tools["mark_known"].annotations)
            templates = await client.list_resource_templates()
            self.assertEqual([t.uri_template for t in templates.resource_templates],
                             ["roadmap://{label}"])
            prompts = await client.list_prompts()
            self.assertEqual([p.name for p in prompts.prompts], ["tutor", "examiner"])

    async def test_a_dict_comes_back_structured(self) -> None:
        async with Client(self.server) as client:
            result = await client.call_tool("next_up", {"source": "subtitle"})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content["unit"]["key"], "merken")
            read = await client.read_resource(f"roadmap://{LABEL}")
            self.assertIn("merken", read.contents[0].text)

    async def test_a_bad_argument_reaches_the_model(self) -> None:
        async with Client(self.server) as client:
            result = await client.call_tool("grade", {"key": "x", "correct": True})
            self.assertTrue(result.is_error)
            self.assertIn("no card for lemma:x", result.content[0].text)


if __name__ == "__main__":
    unittest.main()
