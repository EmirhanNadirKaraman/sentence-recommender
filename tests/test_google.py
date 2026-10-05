"""Signing in with Google: the client's checks, the registry's rules, and the
round trip through a real server with a stand-in for Google's token endpoint.

Nothing here reaches Google. Nothing here builds a reader's application
either: a reader made by a test is checked through the registry, because an
application would open that reader's schema in the real database.
"""
import base64
import hashlib
import hmac
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlencode, urlparse

from readers import ROOT, Registry
from tests import pg
from web.google import (AUTHORIZE, CALLBACK, COOKIE, PENDING_MAX,
                        PENDING_SECONDS, GoogleSignIn, Refused)

CLIENT = "client-id.apps.googleusercontent.com"


def _b64(data: dict | bytes) -> str:
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def token(**claims) -> str:
    """An ID token as Google's token endpoint returns one. Unsigned: the
    client trusts the channel it came by, not a signature."""
    return f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.{_b64(b'sig')}"


class FakeGoogle:
    """Google's token endpoint: answers with `claims`, the nonce filled in
    from the sign-in it is asked about."""

    def __init__(self) -> None:
        self.asked: list[dict] = []
        self.claims: dict = {}
        # The nonce each sign-in went out with, by its verifier: what Google
        # would have kept from the authorization request.
        self.nonces: dict[str, str] = {}
        self.fail = False

    def __call__(self, url: str, fields: dict) -> dict:
        if self.fail:
            raise OSError("no route to Google")
        self.asked.append(dict(fields, url=url))
        nonce = self.nonces.get(fields["code_verifier"], "")
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT,
                  "exp": time.time() + 3600, "nonce": nonce, "sub": "1001",
                  "email": "ahmet@example.com", "email_verified": True}
        claims.update(self.claims)
        return {"id_token": token(**claims)}


def client(base: str = "https://i1.example.org") -> tuple[GoogleSignIn, FakeGoogle]:
    fake = FakeGoogle()
    made = GoogleSignIn(CLIENT, "the secret", base, post=fake)
    began = made.start

    def start(purpose, **fields):
        url, state = began(purpose, **fields)
        pending = made._pending[state]
        fake.nonces[pending.verifier] = pending.nonce
        return url, state

    made.start = start
    return made, fake


class ClientTest(unittest.TestCase):
    def test_the_browser_is_sent_to_google_with_a_pkce_challenge(self) -> None:
        google, _ = client()
        url, state = google.start("signin", next="/roadmap")
        parsed = urlparse(url)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", AUTHORIZE)
        sent = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.assertEqual(sent["client_id"], CLIENT)
        self.assertEqual(sent["redirect_uri"], "https://i1.example.org" + CALLBACK)
        self.assertEqual(sent["response_type"], "code")
        self.assertEqual(sent["scope"], "openid email")
        self.assertEqual(sent["state"], state)
        pending = google._pending[state]
        self.assertEqual(sent["nonce"], pending.nonce)
        self.assertEqual(sent["code_challenge_method"], "S256")
        self.assertEqual(sent["code_challenge"], _b64(
            hashlib.sha256(pending.verifier.encode()).digest()))
        self.assertNotIn("the secret", url)

    def test_the_code_is_traded_with_the_verifier_and_the_secret(self) -> None:
        google, fake = client()
        _, state = google.start("signin")
        verifier = google._pending[state].verifier
        pending, who = google.finish(state, state, "the-code")
        self.assertEqual((pending.purpose, who.subject, who.email),
                         ("signin", "1001", "ahmet@example.com"))
        (asked,) = fake.asked
        self.assertEqual(asked["code"], "the-code")
        self.assertEqual(asked["code_verifier"], verifier)
        self.assertEqual(asked["client_secret"], "the secret")
        self.assertEqual(asked["redirect_uri"], google.redirect_uri)
        self.assertEqual(asked["grant_type"], "authorization_code")

    def test_an_answer_needs_the_cookie_of_the_browser_that_asked(self) -> None:
        google, fake = client()
        _, state = google.start("signin")
        for cookie in ("", "someone-elses-state"):
            with self.assertRaises(Refused):
                google.finish(state, cookie, "code")
        self.assertEqual(fake.asked, [])

    def test_a_state_is_good_once(self) -> None:
        google, _ = client()
        _, state = google.start("signin")
        google.finish(state, state, "code")
        with self.assertRaises(Refused):
            google.finish(state, state, "code")

    def test_a_sign_in_left_too_long_is_refused(self) -> None:
        google, fake = client()
        _, state = google.start("signin")
        later = time.time() + PENDING_SECONDS + 1
        with mock.patch("web.google.time.time", return_value=later):
            with self.assertRaises(Refused):
                google.finish(state, state, "code")
        self.assertEqual(fake.asked, [])

    def test_a_token_not_for_this_site_or_this_sign_in_is_refused(self) -> None:
        for wrong in ({"aud": "someone-else"}, {"iss": "https://evil.example"},
                      {"exp": time.time() - 3600}, {"nonce": "another"},
                      {"sub": ""}):
            with self.subTest(wrong=wrong):
                google, fake = client()
                fake.claims = wrong
                _, state = google.start("signin")
                with self.assertRaises(Refused):
                    google.finish(state, state, "code")

    def test_an_address_google_does_not_vouch_for_is_not_kept(self) -> None:
        google, fake = client()
        fake.claims = {"email_verified": False}
        _, state = google.start("signin")
        _, who = google.finish(state, state, "code")
        self.assertEqual(who.email, "")

    def test_google_not_answering_is_said_plainly(self) -> None:
        google, fake = client()
        fake.fail = True
        _, state = google.start("signin")
        with self.assertRaises(Refused):
            google.finish(state, state, "code")

    def test_sign_ins_under_way_are_bounded(self) -> None:
        google, _ = client()
        for _ in range(PENDING_MAX + 20):
            google.start("signin")
        self.assertEqual(len(google._pending), PENDING_MAX)

    def test_without_its_three_settings_there_is_no_google(self) -> None:
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "x",
                                          "GOOGLE_CLIENT_SECRET": "",
                                          "PUBLIC_URL": "https://x"}):
            self.assertIsNone(GoogleSignIn.from_env())


class RegistryGoogleTest(unittest.TestCase):
    def setUp(self) -> None:
        # The limit these tests expect, whatever the developer's `.env` says.
        limit = mock.patch.dict(os.environ, {"SIGNUP_LIMIT": "10"})
        limit.start()
        self.addCleanup(limit.stop)
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.homes = Path(self._dir.name) / "readers"
        self.registry = Registry(pg.schema(self, "accounts"), homes=self.homes)

    def join(self, name: str, subject: str, **extra):
        return self.registry.join_with_google(
            name, subject, f"{name}@example.com",
            extra.pop("lang", "de"), extra.pop("native", "en"), **extra)

    def test_a_reader_google_signs_in_has_no_password_and_a_session(self) -> None:
        reader = self.join("zoe", "2001")
        self.assertEqual((reader.password, reader.google, reader.joined),
                         ("", "2001", "google"))
        self.assertTrue(reader.home.is_dir())
        self.assertTrue(self.registry.shared)
        self.assertEqual(self.registry.google_reader("2001").name, "zoe")
        self.assertEqual(self.registry.google_email("zoe"), "zoe@example.com")
        value = self.registry.sign(reader, int(time.time()) + 60)
        self.assertEqual(self.registry.session(value).name, "zoe")
        self.assertIsNone(self.registry.login("zoe", ""))

    def test_a_password_reader_signs_exactly_what_they_always_did(self) -> None:
        """So the cookie on your phone survives Google's arrival."""
        self.registry.add("emir", "de", "en")
        self.registry.set_password("emir", "a long password")
        reader = self.registry.get("emir")
        until = int(time.time()) + 60
        before = hmac.new(self.registry._key(),
                          f"emir.{until}.{reader.password}".encode(),
                          hashlib.sha256).hexdigest()
        self.assertEqual(self.registry.sign(reader, until), f"emir.{until}.{before}")

    def test_linking_signs_out_what_the_old_ways_in_signed_in(self) -> None:
        self.registry.add("emir", "de", "en")
        self.registry.set_password("emir", "a long password")
        old = self.registry.sign(self.registry.get("emir"), int(time.time()) + 60)
        self.registry.link_google("emir", "3001", "emir@example.com")
        self.assertIsNone(self.registry.session(old))
        renewed = self.registry.sign(self.registry.get("emir"), int(time.time()) + 60)
        self.assertEqual(self.registry.session(renewed).name, "emir")
        self.registry.unlink_google("emir")
        self.assertEqual(self.registry.get("emir").google, "")

    def test_one_google_account_signs_in_one_reader(self) -> None:
        self.join("zoe", "2001")
        with self.assertRaises(SystemExit):
            self.join("zack", "2001")
        self.registry.add("emir", "de", "en")
        with self.assertRaises(SystemExit):
            self.registry.link_google("emir", "2001", "")
        with self.assertRaises(SystemExit):
            self.join("zoe", "2002")                     # the name is taken

    def test_the_only_way_in_cannot_be_unlinked(self) -> None:
        self.join("zoe", "2001")
        with self.assertRaises(SystemExit):
            self.registry.unlink_google("zoe")

    def test_sign_ups_stop_at_the_limit_and_invitations_do_not_count(self) -> None:
        with mock.patch.dict(os.environ, {"SIGNUP_LIMIT": "1"}):
            self.assertEqual(self.registry.places(), 1)
            self.join("zoe", "2001")
            self.assertEqual(self.registry.places(), 0)
            with self.assertRaises(SystemExit):
                self.join("zack", "2002")
            invited = self.registry.invite("en", "tr")
            reader = self.registry.join_with_google("ayla", "2003", "",
                                                    token=invited)
            self.assertEqual((reader.joined, reader.language), ("invite", "en"))
            self.assertIsNone(self.registry.invitation(invited))

    def test_a_language_is_one_there_is_and_translations_another(self) -> None:
        for lang, native in (("xx", "en"), ("de", "xx"), ("en", "en")):
            with self.subTest(lang=lang, native=native), \
                    self.assertRaises(SystemExit):
                self.join("zoe", "2001", lang=lang, native=native)

    def test_removing_a_reader_takes_their_account_schema_and_files(self) -> None:
        name = f"t{uuid.uuid4().hex[:10]}"
        reader = self.join(name, "2001")
        conn = self.registry._conn()
        with conn as c:
            c.execute(f'CREATE SCHEMA "reader_{name}"')
        self.registry.remove(name)
        self.assertIsNone(self.registry.get(name))
        self.assertIsNone(self.registry.google_reader("2001"))
        self.assertFalse(reader.home.exists())
        with self.registry._conn() as c:
            self.assertIsNone(c.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname = %s",
                (f"reader_{name}",)).fetchone())

    def test_the_owner_is_not_removed(self) -> None:
        self.registry.add("emir", "de", "en", ROOT / "data")
        with self.assertRaises(SystemExit):
            self.registry.remove("emir")
        self.assertIsNotNone(self.registry.get("emir"))


class _Viewer:
    def __init__(self, whose: str) -> None:
        self.whose = whose
        self.lists = None

    def next_up(self, query):
        return f"<p>next for {self.whose}</p>"


class _Viewers:
    def __init__(self, whose: str) -> None:
        self.viewer = _Viewer(whose)

    def pick(self, query):
        return self.viewer


class RoundTripTest(unittest.TestCase):
    """A real server, a stand-in for Google, and the registry it writes."""

    def setUp(self) -> None:
        from web.server import Door, _make_handler
        limit = mock.patch.dict(os.environ, {"SIGNUP_LIMIT": "10"})
        limit.start()
        self.addCleanup(limit.stop)
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.registry = Registry(pg.schema(self, "accounts"),
                                 homes=Path(self._dir.name) / "readers")
        for name in ("emir", "ahmet"):
            self.registry.add(name, "de", "en")
            self.registry.set_password(name, f"{name} password")
        owner = mock.patch.object(self.registry, "owner",
                                  return_value=self.registry.get("emir"))
        owner.start()
        self.addCleanup(owner.stop)
        prepare = mock.patch("db.migrate.prepare", return_value=False)
        prepare.start()
        self.addCleanup(prepare.stop)
        app = mock.Mock()
        app.settings.reader = "emir"
        self.door = Door(app, registry=self.registry, google=None)
        self.door._viewers = {n: _Viewers(n) for n in ("emir", "ahmet", "")}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self.door))
        self.port = self.server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        self.door.google, self.fake = client(f"http://{self.host}")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method: str, path: str, body: str = "",
                headers: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        sent = {"Host": self.host, **(headers or {})}
        if body:
            sent.setdefault("Content-Type", "application/x-www-form-urlencoded")
        conn.request(method, path, body=body.encode(), headers=sent)
        response = conn.getresponse()
        data = response.read().decode("utf-8")
        conn.close()
        return response, data

    def cookies(self, response) -> dict[str, str]:
        out = {}
        for header, value in response.getheaders():
            if header.lower() == "set-cookie":
                name, _, rest = value.partition("=")
                out[name] = rest.split(";")[0]
        return out

    def round_trip(self, form: dict, headers: dict | None = None):
        """Out to Google and back: (the callback's response, the start's)."""
        out, _ = self.request("POST", "/auth/google", urlencode(form),
                              headers=headers)
        self.assertEqual(out.status, 303)
        self.assertTrue(out.getheader("Location").startswith(AUTHORIZE))
        state = self.cookies(out)[COOKIE]
        self.assertIn("Path=/auth/google", out.getheader("Set-Cookie"))
        back, data = self.request(
            "GET", f"{CALLBACK}?{urlencode({'state': state, 'code': 'c'})}",
            headers={"Cookie": f"{COOKIE}={state}"})
        return back, data

    def test_the_door_offers_google(self) -> None:
        _, data = self.request("GET", "/login")
        self.assertIn("Sign in with Google", data)
        self.assertIn("action='/auth/google'", data)

    def test_a_linked_reader_signs_in_with_google(self) -> None:
        self.registry.link_google("ahmet", "1001", "ahmet@example.com")
        back, _ = self.round_trip({"purpose": "signin", "next": "/roadmap"})
        self.assertEqual(back.status, 303)
        self.assertEqual(back.getheader("Location"), "/roadmap")
        session = self.cookies(back)["i1_session"]
        self.assertEqual(self.registry.session(session).name, "ahmet")
        response, data = self.request("GET", "/",
                                      headers={"Cookie": f"i1_session={session}"})
        self.assertIn("next for ahmet", data)

    def test_an_answer_without_its_cookie_signs_nobody_in(self) -> None:
        self.registry.link_google("ahmet", "1001", "")
        out, _ = self.request("POST", "/auth/google", "purpose=signin")
        state = self.cookies(out)[COOKIE]
        back, _ = self.request("GET", f"{CALLBACK}?state={state}&code=c")
        self.assertEqual(back.status, 400)
        self.assertNotIn("i1_session", self.cookies(back))

    def test_a_google_account_nobody_uses_is_told_so(self) -> None:
        back, data = self.round_trip({"purpose": "signin"})
        self.assertEqual(back.status, 403)
        self.assertIn("No account here uses that Google account", data)

    def test_anyone_with_google_signs_up_and_is_signed_in(self) -> None:
        response, data = self.request("GET", "/signup")
        self.assertEqual(response.status, 200)
        self.assertIn("Continue with Google", data)
        back, _ = self.round_trip({"purpose": "signup", "name": "zoe",
                                   "language": "de", "native": "en"})
        self.assertEqual(back.status, 303)
        session = self.cookies(back)["i1_session"]
        reader = self.registry.session(session)
        self.assertEqual((reader.name, reader.joined, reader.google),
                         ("zoe", "google", "1001"))

    def test_a_taken_name_is_said_before_the_trip_to_google(self) -> None:
        response, data = self.request("POST", "/auth/google", urlencode(
            {"purpose": "signup", "name": "ahmet", "language": "de",
             "native": "en"}))
        self.assertEqual(response.status, 400)
        self.assertIn("taken", data)
        self.assertEqual(self.door.google._pending, {})

    def test_sign_ups_closed_turn_strangers_away(self) -> None:
        with mock.patch.dict(os.environ, {"SIGNUP_LIMIT": "0"}):
            response, data = self.request("GET", "/signup")
            self.assertEqual(response.status, 403)
            self.assertIn("closed", data)
            response, _ = self.request("POST", "/auth/google", urlencode(
                {"purpose": "signup", "name": "zoe", "language": "de",
                 "native": "en"}))
            self.assertEqual(response.status, 403)

    def test_a_sign_in_begun_on_another_address_is_sent_to_the_public_one(self) -> None:
        response, _ = self.request("POST", "/auth/google", "purpose=signin",
                                   headers={"Host": "elsewhere:8765"})
        self.assertEqual(response.status, 303)
        self.assertEqual(response.getheader("Location"),
                         f"http://{self.host}/login")
        self.assertEqual(self.door.google._pending, {})

    def test_a_signed_in_reader_links_google_and_keeps_this_device(self) -> None:
        response, _ = self.request("POST", "/login",
                                   "name=emir&password=emir+password&next=%2F")
        old = self.cookies(response)["i1_session"]
        back, _ = self.round_trip({"purpose": "link"},
                                  headers={"Cookie": f"i1_session={old}"})
        # The callback is a fresh request: the session cookie goes with it.
        self.assertEqual(back.status, 403)            # without it, refused
        out, _ = self.request("POST", "/auth/google", "purpose=link",
                              headers={"Cookie": f"i1_session={old}"})
        state = self.cookies(out)[COOKIE]
        back, _ = self.request(
            "GET", f"{CALLBACK}?state={state}&code=c",
            headers={"Cookie": f"{COOKIE}={state}; i1_session={old}"})
        self.assertEqual(back.getheader("Location"), "/settings?account=google")
        self.assertEqual(self.registry.get("emir").google, "1001")
        self.assertIsNone(self.registry.session(old))
        fresh = self.cookies(back)["i1_session"]
        self.assertEqual(self.registry.session(fresh).name, "emir")


if __name__ == "__main__":
    unittest.main()
