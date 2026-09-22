"""The web layer, which had no tests at all.

Most of what broke here recently broke in ways a test would have caught in a
second and a person catches by loading a page and squinting: a link to a route
that was never added, an embed missing the one parameter that makes video play
inline on a phone, a sort that silently falls back.

These are deliberately cheap — no Application, no database, no network. The
handlers that need a corpus are not covered; what is covered is everything
that is a string, a table or a rule.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from web import render, watch
from web.handlers import Viewer

ROOT = Path(__file__).resolve().parents[1]


def routes() -> set[str]:
    """Every path `web.server` will answer, read out of the dispatch itself.

    Parsed rather than listed, so the test cannot drift out of step with the
    thing it is checking.
    """
    src = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
    found = set(re.findall(r'path == "([^"]+)"', src))
    found |= set(re.findall(r'path\.startswith\("([^"]+)"\)', src))
    found |= set(re.findall(r'posted == "([^"]+)"', src))
    # `in (...)` groups, for the icons Safari asks for by several names.
    for group in re.findall(r'path in \(([^)]+)\)', src):
        found |= set(re.findall(r'"([^"]+)"', group))
    return found


class LinkTest(unittest.TestCase):
    """Every internal link points at something that answers.

    This is here because it did not. The reading page's empty state offered
    "review what you have" and linked to `/review`, which was never routed and
    returned a 404 rendered as a page — a dead link nobody meets until the
    corpus runs out.
    """

    def internal_links(self) -> set[str]:
        out: set[str] = set()
        for name in ("handlers.py", "render.py", "watch.py"):
            src = (ROOT / "web" / name).read_text(encoding="utf-8")
            for href in re.findall(r"""href=['"](/[^'"{}<>]*)['"]""", src):
                out.add(href.split("?")[0].rstrip("/") or "/")
            for action in re.findall(r"""action=['"](/[^'"{}<>]*)['"]""", src):
                out.add(action)
        return out

    def test_every_link_resolves(self) -> None:
        known = routes()
        dead = sorted(
            link for link in self.internal_links()
            if link not in known
            and not any(link.startswith(p) for p in known if p.endswith("/"))
        )
        self.assertEqual(dead, [], f"links with no route: {dead}")

    def test_the_nav_is_routable(self) -> None:
        known = routes()
        for href, _ in render.NAV:
            self.assertIn(href, known, f"nav points at {href}")


class EmbedTest(unittest.TestCase):
    """The two YouTube embeds, and the parameters phones care about."""

    def embeds(self) -> list[str]:
        return [watch.player("abc12345678", 0), watch.stage("abc12345678", 61)]

    def test_playsinline_is_set(self) -> None:
        """Without it iOS takes the whole screen when playback starts, which
        hides the captions the page exists to show."""
        for html in self.embeds():
            self.assertIn("playsinline=1", html)

    def test_autoplay_is_delegated(self) -> None:
        """Load-bearing once input is handled by the page: every `playVideo`
        is then programmatic, and without the permission nothing plays."""
        for html in self.embeds():
            self.assertRegex(html, r"allow='[^']*autoplay")

    def test_the_player_can_be_reached_by_script(self) -> None:
        for html in self.embeds():
            self.assertIn("enablejsapi=1", html)
            self.assertIn("id='player'", html)

    def test_it_is_the_no_cookie_host(self) -> None:
        for html in self.embeds():
            self.assertIn("youtube-nocookie.com", html)

    def test_the_video_id_is_escaped(self) -> None:
        self.assertNotIn("<script>", watch.player("a'><script>", 0))


class ShellTest(unittest.TestCase):
    """What `layout` puts in the head, which is most of what makes it an app."""

    def setUp(self) -> None:
        self.page = render.layout("Title", "<p>body</p>")

    def test_it_installs(self) -> None:
        for needed in ("apple-mobile-web-app-capable",
                       "/manifest.webmanifest", "apple-touch-icon"):
            self.assertIn(needed, self.page)

    def test_it_paints_under_the_notch_and_puts_content_back(self) -> None:
        self.assertIn("viewport-fit=cover", self.page)

    def test_zooming_is_not_disabled(self) -> None:
        """Refusing to let someone zoom a page of foreign text is the wrong
        call for this app in particular."""
        self.assertNotIn("user-scalable", self.page)

    def test_nothing_is_fetched_from_a_third_party(self) -> None:
        """A phone with no route to the wider internet spent the whole font
        timeout showing nothing."""
        for host in ("fonts.googleapis", "gstatic", "cdn."):
            self.assertNotIn(host, self.page)

    def test_the_assets_are_stamped(self) -> None:
        self.assertRegex(self.page, r"/static/app\.css\?v=[0-9a-f]{12}")

    def test_the_stamp_follows_the_file(self) -> None:
        self.assertEqual(render.stamped("app.css"), render.stamped("app.css"))
        self.assertNotEqual(render.stamped("app.css"), render.stamped("app.js"))

    def test_the_title_is_escaped(self) -> None:
        # The head carries a script of its own now (the colours switch), so
        # the check is the title itself.
        self.assertIn("<title>&lt;script&gt;</title>", render.layout("<script>", "x"))


class MarkTest(unittest.TestCase):
    def test_it_marks_the_new_word(self) -> None:
        self.assertIn("<span class='target'>Haus</span>",
                      render.mark("Das Haus ist gross.", "Haus"))

    def test_it_escapes_before_marking(self) -> None:
        """Escaping after wrapping would let the sentence break out of it."""
        out = render.mark("<script>alert(1)</script> Haus", "Haus")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)          # escaped, not stripped
        self.assertIn("<span class='target'>Haus</span>", out)

    def test_no_surface_is_no_mark(self) -> None:
        self.assertNotIn("<span class='target'>",
                         render.mark("Das Haus ist gross.", None))


class OrderingTest(unittest.TestCase):
    """The three questions the catalogue can answer, and the fourth."""

    def rows(self) -> list[dict]:
        return [
            {"video": "a", "watch": 0.30, "i+1": 10, "teaches": 2, "minutes": 10},
            {"video": "b", "watch": 0.05, "i+1": 90, "teaches": 40, "minutes": 10},
            {"video": "c", "watch": 0.10, "i+1": 40, "teaches": 30, "minutes": 40},
        ]

    def order(self, by: str, plan: dict | None = None) -> list[str]:
        viewer = Viewer.__new__(Viewer)      # no Application needed
        return [r["video"] for r in viewer._ordered(self.rows(), by, plan)]

    def test_watchability_favours_what_you_already_follow(self) -> None:
        self.assertEqual(self.order("watch")[0], "a")

    def test_density_favours_what_teaches_most(self) -> None:
        """The two disagree, which is the whole reason both are offered."""
        self.assertEqual(self.order("density")[0], "b")

    def test_length_is_divided_out(self) -> None:
        """`c` teaches more than `a` outright and less per minute."""
        self.assertEqual(self.order("density"), ["b", "a", "c"])

    def test_the_plan_wins_when_there_is_one(self) -> None:
        self.assertEqual(self.order("plan", {"c": 1, "a": 2, "b": 3}),
                         ["c", "a", "b"])

    def test_a_video_missing_from_the_plan_sorts_last(self) -> None:
        """It teaches nothing at any point — left out, not hidden."""
        self.assertEqual(self.order("plan", {"b": 1})[0], "b")

    def test_an_unknown_ordering_falls_back(self) -> None:
        self.assertEqual(self.order("nonsense"), self.order("watch"))

    def test_a_video_of_unknown_length_scores_nothing(self) -> None:
        """Rather than dividing by a guess."""
        viewer = Viewer.__new__(Viewer)
        self.assertEqual(viewer._density({"i+1": 50, "minutes": None}), 0.0)


class StoredLabelTest(unittest.TestCase):
    """Which stored plan the page asks for.

    Untested until a `NameError` in it survived a full green run: nothing
    here reaches `_stored_label`, so a plan aimed at the wrong list — or no
    plan at all — looked exactly like a working page. Stubbed rather than
    wired to an Application, like everything else in this file.
    """

    def viewer(self, stored: set[str], goals: str = "study_list"):
        viewer = Viewer.__new__(Viewer)
        viewer.app = SimpleNamespace(
            settings=SimpleNamespace(goal_words=Path(f"data/{goals}.txt")))
        viewer._store = SimpleNamespace(sources=lambda: stored)
        return viewer

    def test_it_prefers_the_well_formed_plan(self) -> None:
        got = self.viewer({"subtitle:good:strict:goals",
                           "subtitle:strict:goals"})
        self.assertEqual(got._stored_label("subtitle", False),
                         "subtitle:good:strict:goals")

    def test_the_counting_mode_chooses(self) -> None:
        both = {"subtitle:strict:goals", "subtitle:list:goals"}
        self.assertEqual(self.viewer(both)._stored_label("subtitle", True),
                         "subtitle:list:goals")
        self.assertEqual(self.viewer(both)._stored_label("subtitle", False),
                         "subtitle:strict:goals")

    def test_a_non_default_list_is_asked_for_by_name(self) -> None:
        """Without the name it served the default list's plan instead, which
        is a different curriculum wearing the right page."""
        stored = {"subtitle:strict:goals", "subtitle:strict:goals:b1_parsed"}
        got = self.viewer(stored, goals="b1_parsed")
        self.assertEqual(got._stored_label("subtitle", False),
                         "subtitle:strict:goals:b1_parsed")

    def test_it_does_not_fall_back_to_another_list(self) -> None:
        """A missing b1 plan is no plan, not the default one."""
        got = self.viewer({"subtitle:strict:goals"}, goals="b1_parsed")
        self.assertEqual(got._stored_label("subtitle", False), "subtitle")


class UnblockedTest(unittest.TestCase):
    """The third counting position, and the one rule it must not break.

    A held plan teaches only what the reader chose. An unblocked one also
    teaches ordinary words standing in the way — which is worth offering and
    wrong to substitute, so it is asked for and never fallen back to.
    """

    def viewer(self, stored: set[str], goals: str = "study_list"):
        viewer = Viewer.__new__(Viewer)
        viewer.app = SimpleNamespace(
            settings=SimpleNamespace(goal_words=Path(f"data/{goals}.txt")))
        viewer._store = SimpleNamespace(sources=lambda: stored)
        return viewer

    def test_it_is_served_when_asked_for(self) -> None:
        stored = {"subtitle:good:strict:goals",
                  "subtitle:good:strict:goals:unblock"}
        got = self.viewer(stored)._stored_label("subtitle", False, True)
        self.assertEqual(got, "subtitle:good:strict:goals:unblock")

    def test_it_is_never_substituted_for_a_held_plan(self) -> None:
        """Asking to be taught your list must not quietly teach other words."""
        stored = {"subtitle:good:strict:goals",
                  "subtitle:good:strict:goals:unblock"}
        got = self.viewer(stored)._stored_label("subtitle", False)
        self.assertEqual(got, "subtitle:good:strict:goals")

    def test_a_missing_unblocked_plan_falls_back_to_the_held_one(self) -> None:
        """The safe direction: stricter than asked for, never looser."""
        got = self.viewer({"subtitle:good:strict:goals"})
        self.assertEqual(got._stored_label("subtitle", False, True),
                         "subtitle:good:strict:goals")

    def test_it_carries_the_word_list_name(self) -> None:
        stored = {"subtitle:good:strict:goals:b1_parsed:unblock"}
        got = self.viewer(stored, goals="b1_parsed")
        self.assertEqual(got._stored_label("subtitle", False, True),
                         "subtitle:good:strict:goals:b1_parsed:unblock")

    def test_the_switch_hides_a_position_with_no_plan(self) -> None:
        """`_stored_label` falls back, so an offered position with nothing
        behind it would serve the plan next door and look like it worked."""
        viewer = self.viewer({"subtitle:good:strict:goals"})
        viewer.source = lambda q: "subtitle"
        html = viewer.counting_switch({}, "/")
        self.assertNotIn("count=unblock", html)
        self.assertIn("count=list", html)

    def test_the_switch_offers_it_when_the_plan_is_there(self) -> None:
        viewer = self.viewer({"subtitle:good:strict:goals",
                              "subtitle:good:strict:goals:unblock"})
        viewer.source = lambda q: "subtitle"
        self.assertIn("count=unblock", viewer.counting_switch({}, "/"))

    def test_the_three_readings_are_exclusive(self) -> None:
        viewer = self.viewer(set())
        for count, listed, opened in (("all", False, False),
                                      ("list", True, False),
                                      ("unblock", False, True)):
            self.assertEqual(viewer.counting({"count": count}), listed, count)
            self.assertEqual(viewer.unblocked({"count": count}), opened, count)

    def test_the_default_is_held_strict_counting(self) -> None:
        viewer = self.viewer(set())
        self.assertFalse(viewer.counting({}))
        self.assertFalse(viewer.unblocked({}))


class LoadedOnceTest(unittest.TestCase):
    """`corpus_for` and `priority`, which exist so a page pays each once.

    The blocked list wants the sentences and nothing else — it builds a
    throwaway index of its own — so asking `scope` for them built an index,
    a builder and an example index that were dropped unused. Splitting them
    only helps if both callers still share one load, which is what these
    check.
    """

    def viewer(self):
        viewer = Viewer.__new__(Viewer)
        viewer._corpora = {}
        viewer._priority = None
        self.loads = []
        self.rankings = 0

        def corpus(*builds, list_only=False, strict=False):
            self.loads.append((builds, list_only, strict))
            return [f"sentence-{len(self.loads)}"]

        def priority():
            self.rankings += 1
            return f"ranking-{self.rankings}"

        viewer.app = SimpleNamespace(corpus=corpus, priority=priority)
        viewer._builds = lambda source: (source,)
        return viewer

    def test_the_same_corpus_is_loaded_once(self) -> None:
        viewer = self.viewer()
        first = viewer.corpus_for("subtitle", False)
        self.assertIs(viewer.corpus_for("subtitle", False), first)
        self.assertEqual(len(self.loads), 1)

    def test_the_counting_mode_is_part_of_the_key(self) -> None:
        """Narrowing gives genuinely different unknown counts, so the two
        readings cannot share a load."""
        viewer = self.viewer()
        self.assertIsNot(viewer.corpus_for("subtitle", True),
                         viewer.corpus_for("subtitle", False))
        self.assertEqual(len(self.loads), 2)

    def test_not_narrowed_asks_for_the_strict_corpus(self) -> None:
        """`list_only=False` means strict, not raw — the duplicate surface
        forms are still dropped."""
        self.viewer().corpus_for("subtitle", False)
        self.assertEqual(self.loads[0], (("subtitle",), False, True))

    def test_narrowed_is_not_also_strict(self) -> None:
        self.viewer().corpus_for("subtitle", True)
        self.assertEqual(self.loads[0], (("subtitle",), True, False))

    def test_the_ranking_is_built_once(self) -> None:
        """`Application.priority` is a fresh build every call, and two of
        the things a page does want the same one."""
        viewer = self.viewer()
        self.assertIs(viewer.priority(), viewer.priority())
        self.assertEqual(self.rankings, 1)


class EverythingTest(unittest.TestCase):
    """"Everything" is `all` on the page and `subtitle+transcript` in a label.

    `build-roadmap --source subtitle transcript` names a plan after the
    builds it walked; `build-roadmap` with no --source names it `all`. The
    same corpus under two names meant the everything position never found a
    plan and quietly walked live instead, showing 316 where the stored plan
    said 347 — a page that looked slow rather than wrong.
    """

    def viewer(self, stored, goals="study_list"):
        viewer = Viewer.__new__(Viewer)
        viewer.app = SimpleNamespace(
            settings=SimpleNamespace(goal_words=Path(f"data/{goals}.txt")))
        viewer._store = SimpleNamespace(sources=lambda: stored)
        viewer.sources = lambda: {"subtitle": 1, "transcript": 1, "all": 2}
        return viewer

    def test_all_finds_a_plan_named_after_its_builds(self) -> None:
        stored = {"subtitle+transcript:good:strict:goals"}
        self.assertEqual(self.viewer(stored)._stored_label("all", False),
                         "subtitle+transcript:good:strict:goals")

    def test_a_plan_actually_named_all_still_wins(self) -> None:
        """Built with no --source, which is what `all` means."""
        stored = {"all:good:strict:goals",
                  "subtitle+transcript:good:strict:goals"}
        self.assertEqual(self.viewer(stored)._stored_label("all", False),
                         "all:good:strict:goals")

    def test_it_carries_the_list_and_the_unblock(self) -> None:
        stored = {"subtitle+transcript:good:strict:goals:b1_parsed:unblock"}
        got = self.viewer(stored, "b1_parsed")._stored_label("all", False, True)
        self.assertEqual(
            got, "subtitle+transcript:good:strict:goals:b1_parsed:unblock")

    def test_a_single_build_source_is_untouched(self) -> None:
        stored = {"subtitle:good:strict:goals"}
        self.assertEqual(self.viewer(stored)._stored_label("subtitle", False),
                         "subtitle:good:strict:goals")

    def test_nothing_stored_still_falls_back_to_the_source(self) -> None:
        self.assertEqual(self.viewer(set())._stored_label("all", False), "all")


class WordListPageTest(unittest.TestCase):
    """`/lists` — the page half of item 9.

    `WordListStore.save` replaces, deliberately, so that removing a word is
    possible at all. Adding therefore has to be read-concat-write, and it
    lives here rather than in the store: the page is the only thing that
    means "and also this".
    """

    def viewer(self, start=()):
        viewer = Viewer.__new__(Viewer)
        self.held = {"mine": list(start)} if start else {}
        store = SimpleNamespace(
            entries=lambda n: tuple(self.held.get(n, ())),
            save=lambda n, e, note="": self.held.__setitem__(n, list(e)),
            forget=lambda n: self.held.pop(n, None),
            names=lambda: [(n, len(v), "now") for n, v in self.held.items()])
        viewer._lists = store
        return viewer

    def post(self, viewer, **form):
        return viewer.save_word_list(form)

    def test_adding_appends_rather_than_replacing(self) -> None:
        viewer = self.viewer(["haus"])
        self.post(viewer, action="add", name="mine", entry="hund")
        self.assertEqual(self.held["mine"], ["haus", "hund"])

    def test_several_ticks_arrive_joined(self) -> None:
        """One checkbox name posted many times; see `web.server.do_POST`."""
        viewer = self.viewer()
        self.post(viewer, action="add", name="mine", entry="haus\x00hund")
        self.assertEqual(self.held["mine"], ["haus", "hund"])

    def test_ticking_nothing_changes_nothing(self) -> None:
        viewer = self.viewer(["haus"])
        self.post(viewer, action="add", name="mine", entry="")
        self.assertEqual(self.held["mine"], ["haus"])

    def test_removing_drops_only_that_entry(self) -> None:
        viewer = self.viewer(["haus", "hund"])
        self.post(viewer, action="remove", name="mine", entry="haus")
        self.assertEqual(self.held["mine"], ["hund"])

    def test_forgetting_takes_the_list(self) -> None:
        viewer = self.viewer(["haus"])
        self.assertEqual(self.post(viewer, action="forget", name="mine"),
                         "/lists")
        self.assertNotIn("mine", self.held)

    def test_a_nameless_post_is_a_no_op(self) -> None:
        """Otherwise a stray form writes a list called empty string."""
        viewer = self.viewer(["haus"])
        self.post(viewer, action="add", name="  ", entry="hund")
        self.assertEqual(self.held, {"mine": ["haus"]})

    def test_it_returns_where_it_came_from(self) -> None:
        viewer = self.viewer()
        self.assertEqual(
            self.post(viewer, action="add", name="mine", entry="x",
                      back="/lists?name=mine&q=hau"),
            "/lists?name=mine&q=hau")


class ComingBackTest(unittest.TestCase):
    """`_here` — the address a form returns to.

    Marking a word reloads the page, and a list forty entries down should
    come back forty entries down.
    """

    def here(self, query: dict, *keys: str) -> str:
        return Viewer.__new__(Viewer)._here("/roadmap", query, *keys)

    def test_it_carries_only_what_it_is_asked_for(self) -> None:
        got = self.here({"page": "3", "q": "haus", "junk": "x"}, "page", "q")
        self.assertIn("page=3", got)
        self.assertIn("q=haus", got)
        self.assertNotIn("junk", got)

    def test_nothing_to_carry_is_a_bare_path(self) -> None:
        self.assertEqual(self.here({}, "page"), "/roadmap")

    def test_empty_values_are_dropped(self) -> None:
        self.assertEqual(self.here({"page": ""}, "page"), "/roadmap")

    def test_it_escapes_what_it_carries(self) -> None:
        self.assertNotIn(" ", self.here({"q": "der Hut"}, "q"))



class MachineCaptionMarkTest(unittest.TestCase):
    """Saying which videos a machine wrote the subtitles for.

    The Studying switch is the filter — pick `video subtitles` and the
    `subtitle:auto` build is not consulted at all — but under `everything`
    both kinds are listed together, and a reader deciding what to watch
    should be able to tell them apart without checking the catalogue.
    """

    def viewer(self, machine=("AUTO1",)):
        from web.handlers import Viewer         # noqa: PLC0415

        # No `__init__`: the marker reads one cached set and nothing else, and
        # building a real Viewer would load a corpus to render a span.
        made = Viewer.__new__(Viewer)
        made._machine = frozenset(machine)
        return made

    def row(self, video: str) -> dict:
        return {"video": video, "minutes": 12.0, "comprehension": 0.61,
                "lines": 240, "i+1": 30, "teaches": 4, "watch": 0.42}

    def test_a_machine_captioned_video_is_marked(self) -> None:
        self.assertIn(">auto<", self.viewer()._wrote_it("AUTO1"))

    def test_a_hand_written_one_is_not(self) -> None:
        self.assertEqual(self.viewer()._wrote_it("MANUAL1"), "")

    def test_the_mark_says_what_it_means_on_hover(self) -> None:
        """`auto` alone reads as a setting rather than a provenance note."""
        self.assertIn("machine-transcribed", self.viewer()._wrote_it("AUTO1"))

    def test_the_reel_says_so_in_the_scoreboard(self) -> None:
        board = self.viewer()._scoreboard(self.row("AUTO1"))
        self.assertIn("machine", board)
        self.assertIn("captions", board)

    def test_a_hand_written_reel_gains_no_cell(self) -> None:
        made = self.viewer()
        self.assertEqual(made._scoreboard(self.row("MANUAL1")).count("<span>"),
                         made._scoreboard(self.row("AUTO1")).count("<span>") - 1)

    def test_the_scoreboard_survives_a_swipe(self) -> None:
        """`reels_json` re-renders the scoreboard; the heading it does not.

        app.js sets the title with `textContent`, which replaces the
        element's children — so a marker put in the heading appeared on load
        and vanished on the first swipe. It lives in the scoreboard for that
        reason, and this is the test that keeps it there.
        """
        import inspect                           # noqa: PLC0415
        from web.handlers import Viewer          # noqa: PLC0415

        reels = inspect.getsource(Viewer.reels)
        self.assertNotIn("_wrote_it", reels)
        self.assertIn("_machine_written",
                      inspect.getsource(Viewer._scoreboard))


class SubtitleWordsTest(unittest.TestCase):
    """A subtitle line is sent as words, each with the unit it wears."""

    def test_each_word_carries_its_unit_and_punctuation_stays_on_it(self) -> None:
        from corpus.sentence import Sentence
        from vocab.entry import Unit
        from web.handlers import _words
        used = Unit.pattern("etw. (Akk) üben")
        line = Sentence("Lasst uns mal kurz üben!",
                        units=frozenset({used, Unit.lemma("kurz"), Unit.lemma("mal")}),
                        surfaces=((used, "Lasst uns üben"), (Unit.lemma("kurz"), "kurz"),
                                  (Unit.lemma("mal"), "mal")))
        self.assertEqual(_words(line), [
            ["Lasst", "pattern", "etw. (Akk) üben"], ["uns", "pattern", "etw. (Akk) üben"],
            ["mal", "lemma", "mal"], ["kurz", "lemma", "kurz"],
            ["üben!", "pattern", "etw. (Akk) üben"]])

    def test_a_sentences_words_are_buttons_and_the_new_word_keeps_its_mark(self) -> None:
        from web.render import sentence
        words = [["Lasst", "pattern", "etw. (Akk) üben"], ["uns", "pattern", "etw. (Akk) üben"],
                 ["kurz", "lemma", "kurz"], ["üben!", "pattern", "etw. (Akk) üben"]]
        html = sentence("Lasst uns kurz üben!", "Let us practise.", "Lasst uns üben",
                        lead=True, words=words)
        self.assertIn("data-text='Lasst uns kurz üben!'", html)
        self.assertIn("class='w target' data-kind='pattern' data-key='etw. (Akk) üben'>Lasst<", html)
        self.assertIn("class='w' data-kind='lemma' data-key='kurz'>kurz<", html)
        self.assertIn("class='w target' data-kind='pattern' data-key='etw. (Akk) üben'>üben!<", html)
        self.assertIn("<p class='en'>Let us practise.</p>", html)

    def test_with_the_known_set_every_other_word_says_whether_it_is_known(self) -> None:
        """Known or new, for the colours; the target stays the target, and a
        word no unit claims is neither."""
        from vocab.entry import Unit
        from web.render import clickable
        words = [["Lasst", "pattern", "etw. (Akk) üben"], ["uns", "", ""],
                 ["mal", "lemma", "mal"], ["kurz", "lemma", "kurz"],
                 ["üben!", "pattern", "etw. (Akk) üben"]]
        html = clickable(words, "Lasst üben", known=frozenset({Unit.lemma("mal")}))
        self.assertIn("class='w target' data-kind='pattern' data-key='etw. (Akk) üben'>Lasst<", html)
        self.assertIn("class='w' data-kind='' data-key=''>uns<", html)
        self.assertIn("class='w known' data-kind='lemma' data-key='mal'>mal<", html)
        self.assertIn("class='w new' data-kind='lemma' data-key='kurz'>kurz<", html)
        self.assertIn("class='w target' data-kind='pattern' data-key='etw. (Akk) üben'>üben!<", html)

    def test_a_word_wears_its_lemma_and_a_pattern_takes_the_rest_or_its_own_word(self) -> None:
        """`Freund` is the lemma, not the frame around it; the frame shows
        on `einen`. A pattern every word of which is somebody's lemma
        takes the word that says its name -- whichever order the surfaces
        come in."""
        from corpus.sentence import Sentence
        from vocab.entry import Unit
        from web.handlers import _words
        have = Unit.pattern("etw./jdn. (Akk) haben")
        alone = Unit.pattern("allein, alleine")
        units = frozenset({have, alone, Unit.lemma("haben"), Unit.lemma("freund"),
                           Unit.lemma("allein")})
        surfaces = ((have, "habe einen Freund"), (alone, "allein"),
                    (Unit.lemma("haben"), "habe"), (Unit.lemma("freund"), "Freund"),
                    (Unit.lemma("allein"), "allein"))
        want = [["Ich", "", ""], ["habe", "lemma", "haben"],
                ["einen", "pattern", "etw./jdn. (Akk) haben"], ["Freund", "lemma", "freund"],
                ["allein.", "pattern", "allein, alleine"]]
        text = "Ich habe einen Freund allein."
        self.assertEqual(_words(Sentence(text, units=units, surfaces=surfaces)), want)
        self.assertEqual(_words(Sentence(text, units=units, surfaces=surfaces[::-1])), want)
        # A frame whose every word is a lemma's: the verb wears it.
        come = Unit.pattern("zu etw. (Dat) kommen")
        line = Sentence("Wir kommen zum Strand.",
                        units=frozenset({come, Unit.lemma("zu"), Unit.lemma("strand"),
                                         Unit.lemma("kommen")}),
                        surfaces=((come, "kommen zum Strand"), (Unit.lemma("zu"), "zum"),
                                  (Unit.lemma("strand"), "Strand"), (Unit.lemma("kommen"), "kommen")))
        self.assertEqual(_words(line), [["Wir", "", ""], ["kommen", "pattern", "zu etw. (Dat) kommen"],
                                        ["zum", "lemma", "zu"], ["Strand.", "lemma", "strand"]])
        # A noun's gender is worn by its article; contracted away, the
        # pattern goes unworn and the noun stays the word.
        beach = Unit.pattern("der Strand")
        line = Sentence("Wir gehen zum Strand.",
                        units=frozenset({beach, Unit.lemma("zu"), Unit.lemma("strand"),
                                         Unit.lemma("gehen")}),
                        surfaces=((beach, "zum Strand"), (Unit.lemma("zu"), "zum"),
                                  (Unit.lemma("strand"), "Strand"), (Unit.lemma("gehen"), "gehen")))
        self.assertEqual(_words(line), [["Wir", "", ""], ["gehen", "lemma", "gehen"],
                                        ["zum", "lemma", "zu"], ["Strand.", "lemma", "strand"]])
        line = Sentence("Ein Strand.", units=frozenset({beach, Unit.lemma("strand")}),
                        surfaces=((beach, "Ein Strand"), (Unit.lemma("strand"), "Strand")))
        self.assertEqual(_words(line), [["Ein", "pattern", "der Strand"], ["Strand.", "lemma", "strand"]])

    def test_a_line_nobody_analysed_is_still_words(self) -> None:
        from corpus.sentence import Sentence
        from web.handlers import _words
        self.assertEqual(_words(Sentence("Na ja.")), [["Na", "", ""], ["ja.", "", ""]])


class ReviewQueueTest(unittest.TestCase):
    """Word cards and your own sentences are one queue, by date: a
    sentence three days overdue is asked before a card due an hour ago."""

    def viewer(self, tmp: Path):
        from context import Application
        from srs import CardStore, SM2Scheduler
        from vocab.attempts import Attempts
        from vocab.own_sentences import OwnSentences
        state = tmp / "state.sqlite3"
        app = SimpleNamespace(
            card_store=CardStore(state), own=OwnSentences(state),
            scheduler=SM2Scheduler(),
            encounters=SimpleNamespace(rungs=lambda: {}, count=lambda unit: 0),
            attempts=Attempts(state),
            mcp_prompt=lambda unit: {"spoken": unit.key, "meaning": "", "examples": []},
            corpus_store=SimpleNamespace(builds=lambda teachable_only=False: {"subtitle": 1}),
            settings=SimpleNamespace(state_path=state, goal_words=tmp / "study_list.txt"))
        app.due_cards = lambda now=None, limit=20: Application.due_cards(app, now, limit)
        viewer = Viewer(app)
        return viewer, app

    def test_a_sentence_overdue_is_asked_before_a_card_due_today(self) -> None:
        import tempfile
        from datetime import datetime, timedelta
        from vocab.entry import Unit
        with tempfile.TemporaryDirectory() as tmp:
            viewer, app = self.viewer(Path(tmp))
            now = datetime.now()
            app.own.add("Ich muss das noch sagen.", "I still have to say this.",
                        now - timedelta(days=3))
            app.card_store.add(app.scheduler.new_card(Unit.lemma("merken"),
                                                      now - timedelta(hours=1)))
            page = viewer.review({})
            self.assertIn("I still have to say this.", page)
            self.assertIn("Yours, to be able to say", page)
            self.assertIn("2 due", page)
            # The German is not on the page until it has been written out.
            self.assertNotIn("Ich muss das noch sagen.</p>", page)
            self.assertIn("name='sentence'", page)
            what, page = viewer.save_review(
                {"text": "Ich muss das noch sagen.", "action": "say",
                 "sentence": "Ich muss das noch sag.", "src": ""})
            self.assertEqual(what, "page")
            # The kept sentence above what was written, and neither graded.
            self.assertIn("<p class='de lead'>Ich muss das noch sagen.</p>", page)
            self.assertIn("<p class='de yours'>Ich muss das noch sag.</p>", page)
            self.assertIn("translate.google.com", page)
            self.assertEqual(app.own.all()[0]["repetitions"], 0)
            # Had it: off the queue, and the word card is next.
            viewer.save_review({"text": "Ich muss das noch sagen.", "action": "good", "src": ""})
            self.assertEqual(app.own.due(now), [])
            page = viewer.review({})
            self.assertNotIn("Yours, to be able to say", page)
            self.assertIn("merken", page)
            self.assertIn("1 due", page)

    def test_a_word_card_asks_for_a_translation_and_shows_the_german_after(self) -> None:
        """An English sentence the word was said in, then the German above
        what was written. Nothing is graded by writing it, and no model is
        asked anything."""
        import tempfile
        from datetime import datetime
        from vocab.entry import Unit
        with tempfile.TemporaryDirectory() as tmp:
            viewer, app = self.viewer(Path(tmp))
            merken = Unit.lemma("merken")
            app.mcp_prompt = lambda unit: {
                "spoken": "merken", "meaning": "to note",
                "examples": [{"text": "Das muss ich mir merken.",
                              "english": "I have to remember that.", "surface": "merken"}]}
            app.card_store.add(app.scheduler.new_card(merken, datetime.now()))
            page = viewer.review({})
            self.assertIn("I have to remember that.", page)
            self.assertIn("Say this in German", page)
            self.assertNotIn("Das muss ich mir merken.<", page)
            what, page = viewer.save_review(
                {"kind": "lemma", "key": "merken", "action": "say",
                 "asked": "Das muss ich mir merken.",
                 "sentence": "Ich muss mir das merken.", "src": ""})
            self.assertEqual(what, "page")
            self.assertIn("Das muss ich mir <span class='target'>merken</span>.", page)
            self.assertIn("<p class='de yours'>Ich muss mir das merken.</p>", page)
            self.assertEqual(app.card_store.get(merken).repetitions, 0)
            self.assertEqual([a["written"] for a in app.attempts.of(merken)],
                             ["Ich muss mir das merken."])
            viewer.save_review({"kind": "lemma", "key": "merken", "action": "good", "src": ""})
            self.assertEqual(app.card_store.get(merken).repetitions, 1)
            self.assertEqual([a["correct"] for a in app.attempts.of(merken)], [True])

    def test_not_this_one_asks_the_next_instead(self) -> None:
        """Skipping decides nothing, so it changes no date -- the one
        passed over is named in the link and goes to the back."""
        import tempfile
        from datetime import datetime, timedelta
        from vocab.entry import Unit
        with tempfile.TemporaryDirectory() as tmp:
            viewer, app = self.viewer(Path(tmp))
            now = datetime.now()
            app.own.add("Ich muss das noch sagen.", "I still have to say this.",
                        now - timedelta(days=3))
            app.card_store.add(app.scheduler.new_card(Unit.lemma("merken"),
                                                      now - timedelta(hours=1)))
            back = viewer.save_review({"text": "Ich muss das noch sagen.",
                                       "action": "skip", "src": "subtitle"})
            self.assertEqual(back, "/review?src=subtitle&not=Ich%20muss%20das%20noch%20sagen.")
            page = viewer.review({"src": "subtitle", "not": "Ich muss das noch sagen."})
            self.assertIn("merken", page)
            self.assertNotIn("I still have to say this.", page)
            # Still due, and asked again once something else has been.
            self.assertIn("2 due", page)
            self.assertIn("I still have to say this.", viewer.review({"src": "subtitle"}))

    def test_a_word_card_is_untouched_by_the_sentence_branch(self) -> None:
        """The two are told apart by what the form carries -- a sentence
        has text and no unit -- so grading one cannot reach the other."""
        import tempfile
        from datetime import datetime, timedelta
        from vocab.entry import Unit
        with tempfile.TemporaryDirectory() as tmp:
            viewer, app = self.viewer(Path(tmp))
            now = datetime.now()
            app.own.add("Ich muss das noch sagen.", "I still have to say this.",
                        now - timedelta(days=3))
            app.card_store.add(app.scheduler.new_card(Unit.lemma("merken"), now))
            viewer.save_review({"text": "Ich muss das noch sagen.", "action": "again", "src": ""})
            self.assertEqual(app.card_store.get(Unit.lemma("merken")).repetitions, 0)
            self.assertEqual(app.own.all()[0]["repetitions"], 0)


class WatchRowsTest(unittest.TestCase):
    """The watch page's transcript is made of word buttons too, each saying
    whether it is known, the spoken line's target marked and only that
    line's; the words ride along on the row for the hearing count."""

    def test_rows_are_words_with_their_knownness(self) -> None:
        from alignment.timing import Timing
        from corpus.sentence import Sentence
        from vocab.entry import Unit
        from web.handlers import _words
        kurz, mal = Unit.lemma("kurz"), Unit.lemma("mal")
        cues = [Sentence("Mal kurz.", units=frozenset({kurz, mal}),
                         surfaces=((kurz, "kurz"), (mal, "Mal"))).with_timing(Timing("v", 1.0, 2.0)),
                Sentence("Kurz mal.", units=frozenset({kurz, mal}),
                         surfaces=((kurz, "Kurz"), (mal, "mal"))).with_timing(Timing("v", 2.0, 3.0))]
        html = watch.transcript(cues, 1, "Kurz", words=_words, known=frozenset({mal}))
        self.assertIn("class='w new' data-kind='lemma' data-key='kurz'>kurz.<", html)
        self.assertIn("class='w known' data-kind='lemma' data-key='mal'>Mal<", html)
        self.assertIn("class='w target' data-kind='lemma' data-key='kurz'>Kurz<", html)
        self.assertIn("data-words=\"[[&quot;Mal&quot;, &quot;lemma&quot;, &quot;mal&quot;], "
                      "[&quot;kurz.&quot;, &quot;lemma&quot;, &quot;kurz&quot;]]\"", html)
        self.assertIn("<script>window.__known={\"lemma:mal\":1};</script>",
                      watch.merged_script(frozenset({mal})))


class HeardTest(unittest.TestCase):
    """Lines the page played through, posted as the transcript sent them,
    become one encounter per word per line."""

    def test_each_word_of_a_heard_line_is_met_once(self) -> None:
        import tempfile
        from vocab.encounters import Encounters
        from vocab.entry import Unit
        with tempfile.TemporaryDirectory() as tmp:
            store = Encounters(Path(tmp) / "state.sqlite3")
            viewer = SimpleNamespace(app=SimpleNamespace(encounters=store))
            got = Viewer.heard(viewer, [
                {"text": "Lasst uns mal üben!", "video": "vid", "at": 12.5,
                 "words": [["Lasst", "pattern", "etw. (Akk) üben"],
                           ["uns", "pattern", "etw. (Akk) üben"], ["mal", "lemma", "mal"],
                           ["üben!", "pattern", "etw. (Akk) üben"], ["Na", "", ""]]},
                "not a line", {"text": "Na ja.", "words": []}])
            self.assertEqual(got, {"heard": 2})
            self.assertEqual(store.count(Unit.pattern("etw. (Akk) üben")), 1)
            self.assertEqual(store.lines(Unit.lemma("mal")),
                             [{"text": "Lasst uns mal üben!", "video": "vid", "at": 12.5,
                               "last": store.lines(Unit.lemma("mal"))[0]["last"]}])
            self.assertEqual({u: r.level for u, r in store.rungs().items()},
                             {Unit.pattern("etw. (Akk) üben"): 1, Unit.lemma("mal"): 1})


if __name__ == "__main__":
    unittest.main()
