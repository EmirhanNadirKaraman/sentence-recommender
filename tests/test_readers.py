"""More than one reader: who they are, how they sign in, whose files are whose.

The first reader's installation has to come through unchanged -- every path
`Settings()` names, the same state file, no login -- and a second reader has
to reach nothing of the first's. The door is tested over a real socket,
because what it guards is what a browser sends, cookies and all.
"""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import time
import unittest
from dataclasses import fields
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from config import ROOT, Settings
from tests import pg
from languages import ENGLISH, GERMAN
from readers import (LOCKOUT_SECONDS, TRIES, Reader, Registry, check_password,
                     hash_password)


class PasswordTest(unittest.TestCase):
    def test_the_right_password_checks_and_a_wrong_one_does_not(self) -> None:
        stored = hash_password("correct horse")
        self.assertTrue(check_password("correct horse", stored))
        self.assertFalse(check_password("correct horse ", stored))

    def test_the_same_password_hashes_differently_each_time(self) -> None:
        self.assertNotEqual(hash_password("same"), hash_password("same"))

    def test_a_malformed_hash_checks_nothing(self) -> None:
        for stored in ("", "plain", "md5$1$2$3$aa$bb"):
            self.assertFalse(check_password("anything", stored))


class RegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name) / "readers"
        self.registry = Registry(pg.schema(self, "accounts"), homes=self.root)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_no_registry_is_one_reader_and_no_login(self) -> None:
        self.assertEqual(self.registry.readers(), {})
        self.assertFalse(self.registry.shared)
        self.assertIsNone(self.registry.default())

    def test_a_reader_gets_a_home_of_their_own(self) -> None:
        reader = self.registry.add("ahmet", "en", "tr")
        self.assertEqual(reader.home, self.root / "ahmet")
        self.assertTrue(reader.home.is_dir())
        self.assertEqual((reader.language, reader.native), ("en", "tr"))

    def test_logging_in_is_only_needed_once_someone_has_a_password(self) -> None:
        self.registry.add("ahmet", "en", "tr")
        self.assertFalse(self.registry.shared)
        self.registry.set_password("ahmet", "a long password")
        self.assertTrue(self.registry.shared)

    def test_the_reader_at_the_top_of_data_is_the_default(self) -> None:
        self.registry.add("emir", "de", "en", home=ROOT / "data")
        self.registry.add("ahmet", "en", "tr")
        self.assertEqual(self.registry.default().name, "emir")

    def test_two_readers_and_neither_at_the_top_means_no_default(self) -> None:
        self.registry.add("one", "de", "en")
        self.registry.add("two", "en", "tr")
        self.assertIsNone(self.registry.default())

    def test_names_that_would_not_survive_a_path_or_a_cookie_are_refused(self) -> None:
        for bad in ("Emir", "a b", "../x", "", "1st", "x" * 40, "a.b"):
            with self.assertRaises(SystemExit, msg=bad):
                self.registry.add(bad, "de", "en")

    def test_an_unknown_language_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            self.registry.add("ahmet", "xx", "tr")
        with self.assertRaises(SystemExit):
            self.registry.add("ahmet", "en", "xx")

    def test_a_name_is_not_taken_twice(self) -> None:
        self.registry.add("ahmet", "en", "tr")
        with self.assertRaises(SystemExit):
            self.registry.add("ahmet", "de", "en")

    def test_a_short_password_is_refused(self) -> None:
        self.registry.add("ahmet", "en", "tr")
        with self.assertRaises(SystemExit):
            self.registry.set_password("ahmet", "short")

    def test_readers_are_in_the_database_and_no_file_is_written(self) -> None:
        self.registry.add("ahmet", "en", "tr")
        self.assertFalse((self.root / "readers.json").exists())
        self.assertEqual(Registry(self.registry._db).names(), ["ahmet"])


class SessionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.registry = Registry(pg.schema(self, "accounts"),
                                 homes=Path(self._dir.name) / "readers")
        self.registry.add("ahmet", "en", "tr")
        self.registry.set_password("ahmet", "a long password")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_a_good_login_is_a_cookie_that_names_the_reader(self) -> None:
        cookie = self.registry.login("ahmet", "a long password")
        self.assertEqual(self.registry.session(cookie).name, "ahmet")

    def test_a_bad_login_is_nothing(self) -> None:
        self.assertIsNone(self.registry.login("ahmet", "wrong password"))
        self.assertIsNone(self.registry.login("nobody", "a long password"))

    def test_a_tampered_cookie_is_nobody(self) -> None:
        name, expires, signature = self.registry.login(
            "ahmet", "a long password").split(".")
        forged = f"{name}.{int(expires) + 10**6}.{signature}"
        self.assertIsNone(self.registry.session(forged))
        self.assertIsNone(self.registry.session("ahmet.123"))
        self.assertIsNone(self.registry.session(""))

    def test_an_expired_cookie_is_nobody(self) -> None:
        reader = self.registry.get("ahmet")
        stale = self.registry.sign(reader, int(time.time()) - 1)
        self.assertIsNone(self.registry.session(stale))

    def test_a_new_password_signs_every_device_out(self) -> None:
        cookie = self.registry.login("ahmet", "a long password")
        self.registry.set_password("ahmet", "another long one")
        self.assertIsNone(self.registry.session(cookie))

    def test_a_cookie_from_another_installation_is_nobody(self) -> None:
        cookie = self.registry.login("ahmet", "a long password")
        with tempfile.TemporaryDirectory() as other:
            elsewhere = Registry(pg.schema(self, "other"),
                                 homes=Path(other) / "readers")
            elsewhere.add("ahmet", "en", "tr")
            elsewhere.set_password("ahmet", "a long password")
            self.assertIsNone(elsewhere.session(cookie))

    def test_too_many_wrong_tries_lock_the_name_right_or_wrong(self) -> None:
        for _ in range(TRIES):
            self.assertIsNone(self.registry.login("ahmet", "guess"))
        self.assertTrue(self.registry.locked("ahmet"))
        self.assertIsNone(self.registry.login("ahmet", "a long password"))
        later = time.time() + LOCKOUT_SECONDS + 1
        with mock.patch("readers.time.time", return_value=later):
            self.assertIsNotNone(self.registry.login("ahmet", "a long password"))


class InvitationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.registry = Registry(pg.schema(self, "accounts"),
                                 homes=Path(self._dir.name) / "readers")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_an_invitation_makes_one_account_and_is_spent(self) -> None:
        token = self.registry.invite("en", "tr")
        self.assertEqual(self.registry.invitation(token)["language"], "en")
        reader = self.registry.redeem(token, "ahmet", "a long password")
        self.assertEqual((reader.language, reader.native), ("en", "tr"))
        self.assertIsNotNone(self.registry.login("ahmet", "a long password"))
        self.assertIsNone(self.registry.invitation(token))
        with self.assertRaises(SystemExit):
            self.registry.redeem(token, "other", "a long password")

    def test_the_token_itself_is_never_stored(self) -> None:
        token = self.registry.invite("en", "tr")
        from state import open_state
        with open_state(self.registry._db) as conn:
            stored = conn.execute("SELECT digest FROM invite").fetchall()
        self.assertNotIn((token,), stored)
        self.assertEqual(len(stored), 1)

    def test_an_expired_invitation_is_nothing(self) -> None:
        token = self.registry.invite("en", "tr", days=1)
        later = time.time() + 2 * 86400
        with mock.patch("readers.time.time", return_value=later):
            self.assertIsNone(self.registry.invitation(token))
            with self.assertRaises(SystemExit):
                self.registry.redeem(token, "ahmet", "a long password")

    def test_a_taken_name_does_not_spend_the_invitation(self) -> None:
        self.registry.add("ahmet", "en", "tr")
        token = self.registry.invite("en", "tr")
        with self.assertRaises(SystemExit):
            self.registry.redeem(token, "ahmet", "a long password")
        self.assertIsNotNone(self.registry.invitation(token))

    def test_an_invited_reader_gets_a_home_of_their_own(self) -> None:
        token = self.registry.invite("de", "en")
        reader = self.registry.redeem(token, "max", "a long password")
        self.assertEqual(reader.home, self.registry._homes / "max")
        self.assertIsNone(self.registry.owner())


class ReaderSettingsTest(unittest.TestCase):
    def test_the_first_reader_has_exactly_the_settings_there_always_were(self) -> None:
        owner = Settings.for_reader(Reader("emir", ROOT / "data", "de", "en"))
        plain = Settings()
        for field in fields(Settings):
            if field.name == "reader":
                continue
            with self.subTest(field=field.name):
                self.assertEqual(getattr(owner, field.name),
                                 getattr(plain, field.name))
        self.assertEqual(owner.reader, "emir")
        # Their state included: a script that builds `Application()` without
        # naming anyone reads theirs, as it read `data/state.sqlite3`.
        self.assertEqual(owner.state.schema, "reader")

    def test_a_second_reader_keeps_their_own_files_at_home(self) -> None:
        home = Path("/tmp/readers/ahmet")
        settings = Settings.for_reader(Reader("ahmet", home, "en", "tr"))
        self.assertEqual(settings.state.schema, "reader_ahmet")
        self.assertEqual(settings.state.name, settings.own.name)
        self.assertEqual(settings.known_words, home / "known_words.txt")
        self.assertEqual(settings.goal_words, home / "study_list.txt")
        self.assertEqual(settings.data_dir, home)
        self.assertEqual((settings.language, settings.native), ("en", "tr"))

    def test_a_second_language_has_a_schema_of_its_own(self) -> None:
        german = Settings.for_reader(Reader("a", Path("/tmp/a"), "de", "en"))
        english = Settings.for_reader(Reader("b", Path("/tmp/b"), "en", "tr"))
        self.assertEqual(german.own.name, english.own.name)
        self.assertEqual(english.own.schema, "en")
        self.assertIn("-c search_path=en", english.own.dsn_kwargs()["options"])
        self.assertIn("options=-c%20search_path%3Den", english.own.url())
        # German's connection is the one it always had.
        self.assertEqual(german.own.dsn_kwargs()["options"],
                         f"-c work_mem={german.own.WORK_MEM}")
        self.assertNotIn("options", german.own.url())
        self.assertEqual(english.function_words, ENGLISH.function_words)
        self.assertEqual(english.ignored_builds, frozenset())
        self.assertIsNone(english.order_words)

    def test_german_keeps_the_names_it_had(self) -> None:
        self.assertEqual(GERMAN.schema, "")
        self.assertEqual(GERMAN.ignored_builds, frozenset({"tatoeba"}))


# --- the door, over a socket ------------------------------------------------


class _Viewer:
    """What a page handler needs, answering with whose it is."""

    def __init__(self, whose: str) -> None:
        self.whose = whose
        self.marked: list[dict] = []
        self.lists = None

    def next_up(self, query):
        return f"<p>next for {self.whose}</p>"

    def next_json(self, query):
        return {"whose": self.whose}

    def mark_known(self, form):
        self.marked.append(form)
        return form.get("back", "/")

    def heard(self, lines):
        return {"whose": self.whose, "lines": len(lines)}

    def add_video(self, form):
        self.marked.append(form)
        return "/subtitles"


class _Viewers:
    def __init__(self, whose: str) -> None:
        self.viewer = _Viewer(whose)

    def pick(self, query):
        return self.viewer


class GuestTest(unittest.TestCase):
    """Everyone but the installation's own reader is rationed."""

    def test_every_reader_but_the_default_one_is_a_guest(self) -> None:
        from web.server import Door
        own, theirs = mock.Mock(guest=None), mock.Mock(guest=None)
        own.settings.reader = "emir"
        Door(own, registry=mock.Mock(), apps={"emir": own, "ahmet": theirs})
        self.assertIsNone(own.guest)
        self.assertTrue(theirs.guest.take("model"))

    def test_an_allowance_runs_out_and_comes_back_after_an_hour(self) -> None:
        from web.limits import Allowance
        clock = [1000.0]
        with mock.patch("web.limits.time.monotonic", lambda: clock[0]):
            allowance = Allowance({"model": 2})
            self.assertTrue(allowance.take("model"))
            self.assertTrue(allowance.take("model"))
            self.assertFalse(allowance.take("model"))
            self.assertTrue(allowance.take("unrationed"))
            clock[0] += 3600
            self.assertTrue(allowance.take("model"))

    def test_a_guest_keeps_one_other_list_open_and_its_ration(self) -> None:
        """Each list is an application of its own, a parser and caches."""
        from web import server
        app = mock.Mock(guest=object())
        app.settings = Settings()
        made = lambda settings: mock.Mock(settings=settings, guest=None)  # noqa: E731
        with mock.patch.object(server, "Viewer", side_effect=lambda a: mock.Mock(app=a)), \
                mock.patch("context.Application", side_effect=made), \
                mock.patch("vocab.word_lists.WordListStore"), \
                mock.patch.object(server.Viewers, "names", return_value=[
                    app.settings.goal_words.stem, "a", "b"]):
            viewers = server.Viewers(app, keep=1)
            first = viewers.pick({"list": "a"})
            self.assertIs(first.app.guest, app.guest)
            viewers.pick({"list": "b"})
            self.assertEqual(sorted(viewers._made),
                             sorted([app.settings.goal_words.stem, "b"]))
            owner = server.Viewers(mock.Mock(guest=None, settings=Settings()))
            for name in ("a", "b"):
                owner.pick({"list": name})
            self.assertEqual(len(owner._made), 3)


class DoorTest(unittest.TestCase):
    """A real server on a spare port, two readers and no corpus."""

    def setUp(self) -> None:
        from web.server import Door, _make_handler
        self._dir = tempfile.TemporaryDirectory()
        self.registry = Registry(pg.schema(self, "accounts"),
                                 homes=Path(self._dir.name) / "readers")
        for name, lang, native in (("emir", "de", "en"), ("ahmet", "en", "tr")):
            self.registry.add(name, lang, native)
            self.registry.set_password(name, f"{name} password")
        app = mock.Mock()
        app.settings.reader = "emir"
        self.door = Door(app, registry=self.registry)
        self.door._viewers = {name: _Viewers(name) for name in ("emir", "ahmet", "")}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self.door))
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever,
                                        daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._dir.cleanup()

    def request(self, method: str, path: str, body: str = "",
                headers: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        sent = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        if body:
            sent.setdefault("Content-Type", "application/x-www-form-urlencoded")
        conn.request(method, path, body=body.encode(), headers=sent)
        response = conn.getresponse()
        data = response.read().decode("utf-8")
        conn.close()
        return response, data

    def sign_in(self, name: str) -> str:
        response, _ = self.request(
            "POST", "/login", f"name={name}&password={name}+password&next=%2F")
        self.assertEqual(response.status, 303)
        cookie = response.getheader("Set-Cookie")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        return cookie.split(";")[0]

    def test_a_page_without_a_session_is_sent_to_sign_in(self) -> None:
        response, _ = self.request("GET", "/roadmap?src=all")
        self.assertEqual(response.status, 303)
        self.assertEqual(response.getheader("Location"),
                         "/login?next=%2Froadmap%3Fsrc%3Dall")

    def test_the_api_without_a_session_says_so_rather_than_redirecting(self) -> None:
        response, data = self.request("GET", "/api/next")
        self.assertEqual(response.status, 401)
        self.assertEqual(json.loads(data), {"error": "signed out"})

    def test_a_post_without_a_session_changes_nothing(self) -> None:
        response, _ = self.request("POST", "/known", "kind=lemma&key=haus")
        self.assertEqual(response.status, 403)
        for viewers in self.door._viewers.values():
            self.assertEqual(viewers.viewer.marked, [])

    def test_the_login_page_and_the_static_files_need_no_session(self) -> None:
        response, data = self.request("GET", "/login")
        self.assertEqual(response.status, 200)
        self.assertIn("name='password'", data)
        response, _ = self.request("GET", "/manifest.webmanifest")
        self.assertEqual(response.status, 200)

    def test_a_wrong_password_is_told_so_and_gets_no_cookie(self) -> None:
        with mock.patch("web.server.time.sleep"):
            response, data = self.request(
                "POST", "/login", "name=ahmet&password=nope&next=%2F")
        self.assertEqual(response.status, 401)
        self.assertIsNone(response.getheader("Set-Cookie"))
        self.assertIn("do not match", data)

    def test_each_reader_is_served_their_own_pages(self) -> None:
        for name in ("emir", "ahmet"):
            cookie = self.sign_in(name)
            response, data = self.request("GET", "/", headers={"Cookie": cookie})
            self.assertEqual(response.status, 200)
            self.assertIn(f"next for {name}", data)
            response, data = self.request("GET", "/api/next",
                                          headers={"Cookie": cookie})
            self.assertEqual(json.loads(data), {"whose": name})

    def test_marking_a_word_lands_with_the_reader_who_marked_it(self) -> None:
        cookie = self.sign_in("ahmet")
        response, _ = self.request("POST", "/known", "kind=lemma&key=house",
                                   headers={"Cookie": cookie})
        self.assertEqual(response.status, 303)
        self.assertEqual(len(self.door._viewers["ahmet"].viewer.marked), 1)
        self.assertEqual(self.door._viewers["emir"].viewer.marked, [])

    def test_what_was_heard_lands_with_the_reader_who_heard_it(self) -> None:
        cookie = self.sign_in("ahmet")
        response, data = self.request(
            "POST", "/api/heard", '[{"text": "x"}]',
            headers={"Cookie": cookie, "Content-Type": "application/json"})
        self.assertEqual(json.loads(data), {"whose": "ahmet", "lines": 1})

    def test_only_the_owner_reaches_past_their_own_schema(self) -> None:
        """Adding a video scrapes with the owner's cookies into the corpus
        every reader shares; recalculating writes everyone's plan file."""
        owner = mock.patch.object(self.registry, "owner",
                                  return_value=self.registry.get("emir"))
        with owner:
            cookie = self.sign_in("ahmet")
            for route in ("/add-video", "/add-channel", "/replan"):
                response, data = self.request("POST", route, "video=abc",
                                              headers={"Cookie": cookie})
                self.assertEqual(response.status, 403, route)
                self.assertIn("Only the owner", data)
            self.assertEqual(self.door._viewers["ahmet"].viewer.marked, [])
            cookie = self.sign_in("emir")
            response, _ = self.request("POST", "/add-video", "video=abc",
                                       headers={"Cookie": cookie})
            self.assertEqual(response.status, 303)
            self.assertEqual(len(self.door._viewers["emir"].viewer.marked), 1)

    def test_a_post_from_another_site_is_refused(self) -> None:
        cookie = self.sign_in("ahmet")
        response, _ = self.request(
            "POST", "/known", "kind=lemma&key=house",
            headers={"Cookie": cookie, "Origin": "https://evil.example"})
        self.assertEqual(response.status, 403)
        self.assertEqual(self.door._viewers["ahmet"].viewer.marked, [])
        response, _ = self.request(
            "POST", "/known", "kind=lemma&key=house",
            headers={"Cookie": cookie, "Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(response.status, 303)

    def test_a_proxy_that_forwards_the_host_is_believed(self) -> None:
        cookie = self.sign_in("ahmet")
        response, _ = self.request(
            "POST", "/known", "kind=lemma&key=house",
            headers={"Cookie": cookie, "Origin": "https://i1.example.org",
                     "X-Forwarded-Host": "i1.example.org"})
        self.assertEqual(response.status, 303)

    def test_a_redirect_never_leaves_the_site(self) -> None:
        cookie = self.sign_in("ahmet")
        for back in ("//evil.example/x", "https://evil.example", "/\\evil.example"):
            response, _ = self.request(
                "POST", "/known", f"kind=lemma&key=house&back={back}",
                headers={"Cookie": cookie})
            self.assertEqual(response.getheader("Location"), "/", back)
        response, _ = self.request(
            "POST", "/login", "name=ahmet&password=ahmet+password"
                              "&next=https%3A%2F%2Fevil.example")
        self.assertEqual(response.getheader("Location"), "/")

    def test_signing_out_clears_the_cookie(self) -> None:
        cookie = self.sign_in("ahmet")
        response, _ = self.request("POST", "/logout", headers={"Cookie": cookie})
        self.assertEqual(response.status, 303)
        self.assertIn("Max-Age=0", response.getheader("Set-Cookie"))

    def test_a_secure_cookie_only_behind_https(self) -> None:
        response, _ = self.request(
            "POST", "/login", "name=ahmet&password=ahmet+password",
            headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", response.getheader("Set-Cookie"))
        response, _ = self.request(
            "POST", "/login", "name=ahmet&password=ahmet+password")
        self.assertNotIn("Secure", response.getheader("Set-Cookie"))

    def test_an_invitation_link_opens_a_form_and_a_dead_one_says_so(self) -> None:
        token = self.registry.invite("en", "tr")
        response, data = self.request("GET", f"/signup?invite={token}")
        self.assertEqual(response.status, 200)
        self.assertIn("English, with Turkish translations", data)
        response, _ = self.request("GET", "/signup?invite=nonsense")
        self.assertEqual(response.status, 410)

    def test_signing_up_makes_the_account_and_signs_it_in(self) -> None:
        token = self.registry.invite("en", "tr")
        self.door._viewers["newbie"] = _Viewers("newbie")
        with mock.patch("db.migrate.prepare", return_value=False) as prepared:
            response, data = self.request(
                "POST", "/signup", f"invite={token}&name=newbie"
                                   "&password=newbie+pass&again=other+pass")
            self.assertEqual(response.status, 400)
            self.assertIn("do not match", data)
            response, _ = self.request(
                "POST", "/signup", f"invite={token}&name=newbie"
                                   "&password=newbie+pass&again=newbie+pass")
        self.assertEqual(response.status, 303)
        prepared.assert_called_with("en")
        cookie = response.getheader("Set-Cookie").split(";")[0]
        response, data = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertIn("next for newbie", data)
        self.assertEqual(self.registry.get("newbie").language, "en")

    def test_changing_a_password_keeps_this_device_and_drops_the_rest(self) -> None:
        here = self.sign_in("ahmet")
        there = self.sign_in("ahmet")
        with mock.patch("web.server.time.sleep"):
            response, _ = self.request(
                "POST", "/password", "current=wrong&password=brand+new+one"
                                     "&again=brand+new+one",
                headers={"Cookie": here})
        self.assertEqual(response.getheader("Location"), "/settings?account=wrong")
        response, _ = self.request(
            "POST", "/password", "current=ahmet+password&password=brand+new+one"
                                 "&again=brand+new+one", headers={"Cookie": here})
        self.assertEqual(response.getheader("Location"), "/settings?account=changed")
        renewed = response.getheader("Set-Cookie").split(";")[0]
        self.assertEqual(self.request("GET", "/", headers={"Cookie": renewed})[0].status, 200)
        self.assertEqual(self.request("GET", "/", headers={"Cookie": there})[0].status, 303)

    def test_only_the_owner_makes_invitations(self) -> None:
        cookie = self.sign_in("ahmet")
        response, _ = self.request("POST", "/invite", "language=en&native=tr",
                                   headers={"Cookie": cookie})
        self.assertEqual(response.status, 403)
        with mock.patch.object(Registry, "owner",
                               return_value=self.registry.get("ahmet")):
            response, data = self.request(
                "POST", "/invite", "language=en&native=tr",
                headers={"Cookie": cookie, "X-Forwarded-Proto": "https",
                         "X-Forwarded-Host": "i1.example.org"})
        self.assertEqual(response.status, 200)
        self.assertIn("https://i1.example.org/signup?invite=", data)

    def test_without_passwords_there_is_no_door(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            self.door.registry = Registry(pg.schema(self, "empty"),
                                          homes=Path(empty) / "readers")
            response, data = self.request("GET", "/")
            self.assertEqual(response.status, 200)
            self.assertIn("next for", data)
            response, _ = self.request("POST", "/known", "kind=lemma&key=x",
                                       headers={"Origin": "https://anywhere"})
            self.assertEqual(response.status, 303)


if __name__ == "__main__":
    unittest.main()
