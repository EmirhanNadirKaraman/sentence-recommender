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
        self.assertNotIn("<script>", render.layout("<script>", "x"))


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


if __name__ == "__main__":
    unittest.main()
