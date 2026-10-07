"""The web viewer, for one reader or several.

Built on `http.server` rather than a framework: the site is six routes and a
form, and a dependency that has to be installed before the results can be
looked at is a worse trade than forty lines of routing.

An installation with no registry of readers is the program as it always
was: one reader, no login, loopback by default -- binding it anywhere else
puts what it holds on the network for anyone who can reach the port, and
`serve --host` says so out loud when it is used.

Once readers are registered with passwords (`python main.py reader`), every
page but the login page and the static files wants a session cookie, and
each reader is served from their own `Viewers` -- their own known set,
cards, plans and corpus -- so nothing one of them does reaches the other.
That is the front door a server on the open internet needs, and it is the
only one: HTTPS belongs to whatever proxy stands in front of this.
"""
from __future__ import annotations

import os
import socket
import time
import webbrowser
from collections import OrderedDict
from contextlib import contextmanager
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, quote, unquote, urlparse

from readers import SESSION_SECONDS as _SESSION_SECONDS
from web import render
from web.google import COOKIE as _GOOGLE_COOKIE
from web.google import COOKIE_PATH as _GOOGLE_PATH
from web.google import PENDING_SECONDS as _GOOGLE_SECONDS
from web.handlers import Viewer

LOOPBACK = "127.0.0.1"

TYPES = {
    ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/png",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".woff2": "font/woff2", ".json": "application/json; charset=utf-8",
}

# The session cookie. `__Host-` would pin it to this host and path, and is
# refused by browsers over plain HTTP, which is what a proxy speaks to us.
COOKIE = "i1_session"

# What anyone may fetch without a session: the door itself, and the files a
# browser asks for before it has one -- an icon on a home screen, the
# manifest of an installed app.
OPEN = {"/login", "/signup", "/favicon.ico", "/apple-touch-icon.png",
        "/apple-touch-icon-precomposed.png", "/manifest.webmanifest",
        "/auth/google/callback"}

# `Door`'s default for `google`: read the configuration from `.env`.
_FROM_ENV = object()

# What only the installation's owner may do, because it reaches past the
# reader's own schema: adding a video or a channel scrapes YouTube with the
# owner's browser cookies and writes the corpus every reader of the language
# shares, and recalculating writes the plan file every reader's Plan page
# reads.
OWNER_ONLY = {"/add-video", "/add-channel", "/replan"}


class Viewers:
    """One `Viewer` per goal list, built when first asked for.

    A viewer holds everything derived from a list — the resolved goals, the
    narrowed corpus, the ranking, the scopes — so switching lists is a
    different viewer rather than a re-keying of every cache inside one. It
    also means a list nobody opens costs nothing, which matters: each one is
    a corpus load, and that was the measured objection to putting a list
    dimension inside `_scopes`.
    """

    def __init__(self, app, keep: int | None = None) -> None:
        self._default = app
        self._stem = app.settings.goal_words.stem
        self._made: dict[str, Viewer] = {self._stem: Viewer(app)}
        # How many other lists stay open at once, least recently used going
        # first; None for the owner, who may keep every one. See
        # `web.limits.LISTS_OPEN`.
        self._keep = keep
        # Two first requests for the same list at once would otherwise make
        # two viewers, and each loads the corpus.
        self._lock = Lock()

    def names(self) -> list[str]:
        """The list this process was started with, and every saved one."""
        from vocab.word_lists import WordListStore       # noqa: PLC0415
        saved = [n for n, count, _ in
                 WordListStore(self._default.settings.state).names()
                 if count]
        return [self._stem] + [n for n in saved if n != self._stem]

    def pick(self, query: dict) -> Viewer:
        wanted = (query.get("list") or "").strip() or self._stem
        if wanted not in self.names() or self._keep == 0:
            wanted = self._stem
        with self._lock:
            if wanted not in self._made:
                from dataclasses import replace              # noqa: PLC0415
                from context import Application              # noqa: PLC0415
                from vocab.word_lists import WordListStore   # noqa: PLC0415
                store = WordListStore(self._default.settings.state)
                settings = replace(
                    self._default.settings,
                    goal_words=self._default.settings.data_dir / f"{wanted}.txt",
                    goal_entries=store.entries(wanted))
                made = Application(settings)
                made.corpus_pool = self._default.corpus_pool
                # The same reader, so the same allowance: a list is not a
                # way round the model's ration.
                made.guest = self._default.guest
                self._made[wanted] = Viewer(made)
                self._bound(wanted)
            else:
                # Most recently used last, so the oldest is first to go.
                self._made[wanted] = self._made.pop(wanted)
        viewer = self._made[wanted]
        viewer.lists = self                              # for the switch
        return viewer

    def _bound(self, opened: str) -> None:
        """Keep `keep` lists besides the reader's own -- the one just opened
        among them -- dropping the least recently used. A request still
        holding a dropped one finishes with it; nothing else does."""
        if self._keep is None:
            return
        others = [n for n in self._made if n not in (self._stem, opened)]
        for name in others[:max(0, len(others) - (self._keep - 1))]:
            del self._made[name]


class Door:
    """Who is asking, and each reader's own viewers.

    Without a registry there is one reader and no question to ask: every
    request is theirs, as it always was. With one, a request belongs to the
    reader its session cookie names, and to nobody without it.
    """

    def __init__(self, app, registry=None, apps: dict | None = None,
                 google=_FROM_ENV) -> None:
        from readers import Registry                     # noqa: PLC0415
        self.registry = registry if registry is not None else Registry()
        # Signing in with Google, when `.env` configures it (`web.google`);
        # None, and no Google button anywhere, when it does not.
        if google is _FROM_ENV:
            from web.google import GoogleSignIn          # noqa: PLC0415
            google = GoogleSignIn.from_env()
        self.google = google
        self._default = app
        from corpus.shared import CorpusPool
        self._corpus_pool = CorpusPool()
        app.corpus_pool = self._corpus_pool
        # Applications already made -- by `serve`, which warms each reader
        # before opening the socket -- so the first page does not make them
        # again.
        self._apps = dict(apps or {})
        # Everyone but the installation's own reader is a guest: rationed
        # (see `web.limits`), and kept from what reaches past their schema.
        for name, made in self._apps.items():
            made.corpus_pool = self._corpus_pool
            if made is not app:
                self._make_guest(made)
        self._viewers: dict[str, Viewers] = {}
        self._lock = Lock()
        # Readers who signed up on their own and are held in memory, least
        # recently reading first (`web.limits.SIGNUPS_IN_MEMORY`), and the
        # ones whose pages have been built since they were last let go.
        self._signed_up: OrderedDict[str, None] = OrderedDict()
        self._built: set[str] = set()
        # One such reader's first page built at a time: it walks the whole
        # corpus, 25 s of a core, and two at once would starve every other
        # page of the process's one interpreter.
        self._building = Lock()

    @property
    def shared(self) -> bool:
        return self.registry.shared

    def viewers(self, reader=None) -> Viewers:
        """`reader`'s viewers, made on first use; the default reader's when
        there is no registry to name anyone."""
        name = reader.name if reader is not None else ""
        signed_up = reader is not None and reader.joined == "google"
        with self._lock:
            if signed_up:
                self._hold(name)
            if name not in self._viewers:
                from web.limits import (LISTS_OPEN,          # noqa: PLC0415
                                        LISTS_OPEN_SIGNED_UP)
                app = self._app_for(reader)
                keep = (None if app.guest is None else
                        LISTS_OPEN_SIGNED_UP if signed_up else LISTS_OPEN)
                self._viewers[name] = Viewers(app, keep=keep)
            return self._viewers[name]

    def _hold(self, name: str) -> None:
        """`name` most recently reading; let go of whoever is past
        `SIGNUPS_IN_MEMORY`. A request still holding their pages finishes
        with them, and their next request builds them again."""
        from web.limits import signups_in_memory         # noqa: PLC0415
        self._signed_up.pop(name, None)
        self._signed_up[name] = None
        while len(self._signed_up) > signups_in_memory():
            gone, _ = self._signed_up.popitem(last=False)
            self._viewers.pop(gone, None)
            self._apps.pop(gone, None)
            self._built.discard(gone)

    @contextmanager
    def building(self, reader):
        """Around a page: for someone who signed up on their own and whose
        pages are not built yet, wait for any other such build to finish."""
        name = reader.name if reader is not None else ""
        if reader is None or reader.joined != "google" or name in self._built:
            yield
            return
        with self._building:
            yield
            self._built.add(name)

    def is_owner(self, reader) -> bool:
        """Whether `reader` runs this installation. Nobody signed in, on an
        installation without readers, is the one reader there is."""
        if reader is None:
            return not self.shared
        owner = self.registry.owner()
        return owner is not None and owner.name == reader.name

    def _app_for(self, reader):
        if reader is None or reader.name == self._default.settings.reader:
            return self._default
        if reader.name not in self._apps:
            from config import Settings                  # noqa: PLC0415
            from context import Application              # noqa: PLC0415
            self._apps[reader.name] = self._make_guest(
                Application(Settings.for_reader(reader)))
            self._apps[reader.name].corpus_pool = self._corpus_pool
        return self._apps[reader.name]

    @staticmethod
    def _make_guest(app):
        from web.limits import Allowance                 # noqa: PLC0415
        app.guest = Allowance()
        return app


class LocalServer:
    """Routes requests to `Viewer` and serves the HTML it returns."""

    def __init__(self, app, port: int = 8765, host: str = LOOPBACK,
                 apps: dict | None = None) -> None:
        self._door = Door(app, apps=apps)
        self._port = port
        self._host = host

    def serve(self, open_browser: bool = True) -> None:
        handler = _make_handler(self._door)
        server = ThreadingHTTPServer((self._host, self._port), handler)
        where = self._reachable_at()
        url = f"http://{where}:{self._port}/"
        # Flushed, both of them. Redirected output is block-buffered, so the
        # one line whose entire job is telling you what to type into the other
        # device is the one that vanishes under nohup, ssh or a service
        # manager — which is exactly where it is needed.
        print(f"serving {url}  (ctrl-c to stop)", flush=True)
        # Keyed on where it is reachable, not where it is bound. In a
        # container the bind is always `0.0.0.0` and this fired every time,
        # while compose publishes on loopback and nobody else could reach it.
        if self._door.shared:
            able = [r.name for r in self._door.registry.readers().values()
                    if r.password or r.google]
            print(f"  readers: {', '.join(sorted(able))} — each signs in",
                  flush=True)
            if self._door.google is not None:
                print(f"  Google sign-in at {self._door.google.base_url}; "
                      f"{self._door.registry.places()} places left to sign up",
                      flush=True)
        elif where != LOOPBACK:
            print("  no authentication — anyone who can reach this port can "
                  "read your corpus and mark words known. `python main.py "
                  "reader add` gives it a login", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            server.server_close()

    def _reachable_at(self) -> str:
        """The address to type into the other device.

        The mDNS name rather than the LAN address, and deliberately: an
        installed web app has no address bar and no reload, so when the DHCP
        lease moves the app is bricked with nothing to edit. `.local` follows
        the machine.

        A bind address is not one of these — `0.0.0.0` means "every
        interface", which is not somewhere a phone can be pointed.

        `SERVE_ANNOUNCE` wins over all of it, because inside a container none
        of this is knowable from within: the bind is `0.0.0.0`, the hostname
        is a random container id, and `<id>.local` resolves nowhere at all.
        Which address the port is published on is a fact only compose holds,
        so compose passes it in.
        """
        announced = os.environ.get("SERVE_ANNOUNCE", "").strip()
        if announced:
            return announced
        if self._host == LOOPBACK:
            return self._host
        if self._host not in ("0.0.0.0", "::", ""):
            return self._host
        name = socket.gethostname()
        return name if name.endswith(".local") else f"{name}.local"


def _make_handler(door: "Door"):
    """One handler; the reader and the goal list chosen per request.

    The reader comes from the session cookie, when the installation has
    readers to sign in. `?list=NAME` picks the list; the form carries the
    same key back so a POST lands on the list the page was showing rather
    than on the default.
    """
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reader(self):
            """The signed-in reader, or None."""
            try:
                jar = SimpleCookie(self.headers.get("Cookie", ""))
            except CookieError:
                return None
            morsel = jar.get(COOKIE)
            return door.registry.session(morsel.value) if morsel else None

        def _admit(self, path: str, posting: bool):
            """(allowed, reader): who this request is from, and whether it
            may go on. Answers the refusal itself when it may not."""
            render.ACTIVE.reader = ""
            render.ACTIVE.shared = False
            if not door.shared:
                return True, None
            render.ACTIVE.shared = True
            reader = self._reader()
            if reader is not None:
                render.ACTIVE.reader = reader.name
                return True, reader
            if posting:
                self._send(_signed_out(), status=403)
            elif path.startswith("/api/"):
                self._send_json({"error": "signed out"}, status=401)
            else:
                self._redirect("/login?next=" + quote(self.path, safe=""))
            return False, None

        def _same_origin(self) -> bool:
            """Whether a POST came from one of this site's own pages.

            The session cookie is `SameSite=Lax`, so a browser will not send
            it with a form another site submits here -- this is the second
            lock, for a browser that ignores the first. A request with no
            `Origin` is a script, not a page someone was tricked into.
            """
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            hosts = {self.headers.get("Host", ""),
                     self.headers.get("X-Forwarded-Host", "")} - {""}
            if urlparse(origin).netloc in hosts:
                return True
            print(f"refused a POST from {origin!r} (host {sorted(hosts)}) — "
                  "a proxy in front must pass Host or X-Forwarded-Host "
                  "through", flush=True)
            return False

        def log_message(self, fmt, *args):        # quiet; the terminal is the user's
            pass

        def handle_one_request(self):
            """Ignore a client that hangs up mid-response.

            A browser cancelling a request — navigating away, or dropping a
            speculative connection — is normal and not worth a traceback.
            """
            try:
                super().handle_one_request()
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def do_GET(self) -> None:                 # noqa: N802 — http.server's API
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            path = parsed.path.rstrip("/") or "/"
            try:
                if path.startswith("/static/") or path in OPEN:
                    html, status = self._route_open(path, query)
                else:
                    allowed, reader = self._admit(path, posting=False)
                    if not allowed:
                        return
                    viewers = door.viewers(reader)
                    with door.building(reader):
                        html, status = self._route(path, query, viewers)
                if status:                     # 0 means the route already replied
                    self._send(html, status)
            except (BrokenPipeError, ConnectionResetError):
                # The reader hung up while this was being built or sent —
                # navigating away, reloading, or simply tired of waiting for
                # a page that takes seconds cold. `handle_one_request` knows
                # to treat that as ordinary, but only if it is allowed to see
                # it: caught here as a generic error it printed a traceback
                # for something nobody did wrong, and then tried to send a
                # 500 down the same closed socket, which raised again.
                raise
            except Exception as error:            # noqa: BLE001 — show it, don't die
                _report(error, self.path)
                self._send(_oops(error), status=500)

        def do_POST(self) -> None:                # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8")
            posted = urlparse(self.path).path.rstrip("/")
            if door.shared and not self._same_origin():
                self._send(_signed_out(), status=403)
                return
            # Joined rather than truncated: a set of checkboxes posts one name
            # many times, and keeping only the first silently drops the rest.
            form = ({} if posted == "/api/heard" else
                    {k: "\x00".join(v) for k, v in parse_qs(body).items()})
            if posted == "/login":
                self._login(form)
                return
            if posted == "/logout":
                self._logout()
                return
            if posted == "/signup":
                self._signup(form)
                return
            if posted == "/auth/google":
                self._google_start(form)
                return
            allowed, reader = self._admit(posted, posting=True)
            if not allowed:
                return
            if posted == "/auth/google/unlink":
                self._google_unlink(reader)
                return
            if posted == "/password":
                self._password(form, reader)
                return
            if posted == "/invite":
                self._invite(form, reader)
                return
            if posted in OWNER_ONLY and not door.is_owner(reader):
                self._send(render.owner_only(), status=403)
                return
            viewers = door.viewers(reader)
            if posted == "/api/heard":
                # JSON, not a form: the page sends the lines it played
                # through, a batch at a time and once more on leaving.
                import json                                  # noqa: PLC0415
                try:
                    heard = json.loads(body or "[]")
                except ValueError:
                    heard = []
                self._send_json(viewers.pick({}).heard(heard))
                return
            viewer = viewers.pick(form)
            try:
                if posted == "/known":
                    back = viewer.mark_known(form)
                    if "application/json" in self.headers.get("Accept", ""):
                        self._send_json({"redirect": back, "journey": viewer.journey_json()})
                    else:
                        self._redirect(back)
                elif posted == "/add-video":
                    self._redirect(viewer.add_video(form))
                elif posted == "/add-channel":
                    self._redirect(viewer.add_channel(form))
                elif posted == "/quiz":
                    self._redirect(viewer.answer_quiz(form))
                elif posted == "/taste":
                    self._redirect(viewer.set_taste(form))
                elif posted == "/hear":
                    self._redirect(viewer.save_hearing(form))
                elif posted == "/replan":
                    self._redirect(viewer.replan(form))
                elif posted == "/remove-video":
                    self._redirect(viewer.remove_video(form))
                elif posted == "/blacklist":
                    self._redirect(viewer.set_blacklist(form))
                elif posted == "/hide":
                    self._redirect(viewer.hide_sentence(form))
                elif posted == "/api/anki":
                    # Two callers, two answers. The button on a word is
                    # JavaScript and wants JSON, because a reload would lose
                    # the reader's place; Remove on the Anki page is a plain
                    # form and says where to come back to.
                    answer = viewer.queue_anki(form)
                    if form.get("back"):
                        self._redirect(form["back"])
                    else:
                        self._send_json(answer)
                elif posted == "/api/star":
                    self._send_json(viewer.star_sentence(form))
                elif posted == "/api/try":
                    self._send_json(viewer.try_json(form))
                elif posted == "/api/cover":
                    self._send_json(viewer.cover_json(form))
                elif posted == "/review":
                    outcome = viewer.save_review(form)
                    if isinstance(outcome, tuple):
                        self._send(outcome[1], 200)
                    else:
                        self._redirect(outcome)
                elif posted == "/mine":
                    outcome = viewer.save_mine(form)
                    if isinstance(outcome, tuple):
                        self._send(outcome[1], 200)
                    else:
                        self._redirect(outcome)
                elif posted == "/fix":
                    self._redirect(viewer.save_fix(form))
                elif posted == "/lists":
                    self._redirect(viewer.save_word_list(form))
                else:
                    self._send(_missing(self.path), status=404)
            except Exception as error:            # noqa: BLE001
                _report(error, self.path)
                self._send(_oops(error), status=500)

        def _redirect(self, target: str, cookie: str | list[str] = "") -> None:
            """303 after a state change, so a refresh does not repeat it.

            Only ever to a path on this site. Several forms say where to come
            back to in a `back` field, and a target taken from a form as it
            stands is a link that sends a reader anywhere at all.
            """
            self._see_other(_local(target), cookie)

        def _away(self, url: str, cookie: str | list[str] = "") -> None:
            """303 off this site: to Google, or to `PUBLIC_URL`. Only for
            addresses this server makes, never one a form gave it."""
            self._see_other(url, cookie)

        def _see_other(self, location: str, cookie: str | list[str]) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            for each in ([cookie] if isinstance(cookie, str) else cookie):
                if each:
                    self.send_header("Set-Cookie", each)
            self.send_header("Content-Length", "0")
            self.end_headers()

        # --- the door --------------------------------------------------

        def _login(self, form: dict) -> None:
            name = (form.get("name") or "").strip().lower()
            password = form.get("password") or ""
            target = _local(form.get("next") or "/")
            value = door.registry.login(name, password) if door.shared else None
            if value is None:
                # A second's wait on every miss, so a guesser cannot hurry;
                # a person who mistyped does not notice it.
                time.sleep(1)
                locked = door.registry.locked(name)
                self._send(render.login_page(
                    "Too many tries -- wait a quarter of an hour." if locked
                    else "That name and password do not match.",
                    target, name, google=door.google is not None), status=401)
                return
            self._redirect(target, self._cookie(value, _SESSION_SECONDS))

        def _logout(self) -> None:
            self._redirect("/login", self._cookie("", 0))

        def _signup(self, form: dict) -> None:
            """An invitation spent: the account made, and signed in."""
            token = form.get("invite") or ""
            name = (form.get("name") or "").strip().lower()
            password = form.get("password") or ""
            found = door.registry.invitation(token)
            if found is None:
                self._send(render.invitation_gone(), status=410)
                return
            google = door.google is not None
            if password != (form.get("again") or ""):
                self._send(render.signup_page(
                    "The two passwords do not match.", token, found, name,
                    google=google), status=400)
                return
            try:
                from db.migrate import prepare           # noqa: PLC0415
                prepare(found["language"])
                reader = door.registry.redeem(token, name, password)
            except SystemExit as refused:
                self._send(render.signup_page(str(refused), token, found, name,
                                              google=google), status=400)
                return
            value = door.registry.sign(reader, int(time.time()) + _SESSION_SECONDS)
            self._redirect("/", self._cookie(value, _SESSION_SECONDS))

        def _password(self, form: dict, reader) -> None:
            """A new password, and this device kept signed in under it."""
            from readers import check_password             # noqa: PLC0415
            if reader is None:
                self._redirect("/settings")
                return
            fresh = form.get("password") or ""
            # Someone who signs in with Google sets a first password without
            # one to give; anyone else proves the one they have.
            if reader.password and not check_password(form.get("current") or "",
                                                      reader.password):
                time.sleep(1)
                self._redirect("/settings?account=wrong")
                return
            if fresh != (form.get("again") or ""):
                self._redirect("/settings?account=mismatch")
                return
            try:
                door.registry.set_password(reader.name, fresh)
            except SystemExit:
                self._redirect("/settings?account=short")
                return
            renewed = door.registry.get(reader.name)
            value = door.registry.sign(renewed, int(time.time()) + _SESSION_SECONDS)
            self._redirect("/settings?account="
                           + ("changed" if reader.password else "set"),
                           self._cookie(value, _SESSION_SECONDS))

        def _invite(self, form: dict, reader) -> None:
            """A link for someone new, made by the installation's owner."""
            owner = door.registry.owner()
            if reader is None or owner is None or reader.name != owner.name:
                self._send(_signed_out(), status=403)
                return
            try:
                token = door.registry.invite(form.get("language") or "en",
                                             form.get("native") or "tr")
            except SystemExit as refused:
                self._send(render.layout("Invite", f"<h1>Invite</h1><p class='note "
                                         f"due'>{render.escape(str(refused))}</p>"),
                           status=400)
                return
            scheme = self.headers.get("X-Forwarded-Proto") or "http"
            host = (self.headers.get("X-Forwarded-Host")
                    or self.headers.get("Host") or "")
            found = door.registry.invitation(token)
            self._send(render.invited_page(
                f"{scheme}://{host}/signup?invite={token}", found), 200)

        # --- Google -----------------------------------------------------
        #
        # Three ways in through one round trip: signing in, signing up, and
        # linking an account to the reader signed in. What each needs goes
        # out with the state (`web.google.Pending`) and comes back with it.

        def _google_start(self, form: dict) -> None:
            google = door.google
            if google is None:
                self._send(_missing(self.path), status=404)
                return
            purpose = form.get("purpose") or "signin"
            if self._host() != google.host:
                # Google answers at `PUBLIC_URL` only, and only a cookie set
                # there can meet the answer: begin again at that address.
                where = "/settings" if purpose == "link" else "/login"
                self._away(google.base_url + where)
                return
            if purpose == "signin":
                fields = {"next": _local(form.get("next") or "/")}
            elif purpose == "link":
                reader = self._reader() if door.shared else None
                if reader is None:
                    self._send(_signed_out(), status=403)
                    return
                fields = {"name": reader.name, "next": "/settings"}
            elif purpose == "signup":
                fields = self._google_signup(form)
                if fields is None:
                    return
            else:
                self._send(_missing(self.path), status=404)
                return
            url, state = google.start(purpose, **fields)
            self._away(url, self._google_cookie(state, _GOOGLE_SECONDS))

        def _google_signup(self, form: dict) -> dict | None:
            """What a sign-up takes to Google and back, checked before it
            goes: a name taken, or no places left, is said now rather than
            after a trip to Google. None when the page has been answered."""
            from readers import NAME, _check_languages      # noqa: PLC0415
            token = form.get("invite") or ""
            name = (form.get("name") or "").strip().lower()
            if token:
                found = door.registry.invitation(token)
                if found is None:
                    self._send(render.invitation_gone(), status=410)
                    return None
                lang, native = found["language"], found["native"]

                def again(error: str) -> str:
                    return render.signup_page(error, token, found, name,
                                              google=True)
            else:
                if not self._open_signup():
                    self._send(render.signup_closed(), status=403)
                    return None
                lang = form.get("language") or ""
                native = form.get("native") or ""

                def again(error: str) -> str:
                    return render.open_signup_page(error, name, lang, native)
            error = ""
            if not NAME.match(name):
                error = ("A name is lowercase letters, digits, - and _, "
                         "starting with a letter.")
            elif door.registry.get(name) is not None:
                error = f"The name {name} is taken."
            elif not token:
                try:
                    _check_languages(lang, native)
                except SystemExit as refused:
                    error = str(refused).capitalize() + "."
            if error:
                self._send(again(error), status=400)
                return None
            return {"name": name, "language": lang, "native": native,
                    "invite": token}

        def _open_signup(self) -> bool:
            """Whether someone may sign up here on their own: Google is set
            up, the installation has its owner -- or the first stranger
            would make it theirs -- and there are places left."""
            return (door.google is not None and door.registry.owner() is not None
                    and door.registry.places() > 0)

        def _google_back(self, query: dict) -> tuple[str, int]:
            """Where Google sends the browser back to."""
            from web.google import Refused                  # noqa: PLC0415
            google = door.google
            if google is None:
                return _missing(self.path), 404
            if query.get("error"):
                return render.google_failed(
                    "Google sign-in was cancelled, so nothing changed.",
                    "/login"), 400
            try:
                pending, who = google.finish(query.get("state") or "",
                                             self._cookie_named(_GOOGLE_COOKIE),
                                             query.get("code") or "")
            except Refused as why:
                return render.google_failed(str(why), "/login"), 400
            spent = self._google_cookie("", 0)
            until = int(time.time()) + _SESSION_SECONDS
            if pending.purpose == "signin":
                reader = door.registry.google_reader(who.subject)
                if reader is None:
                    return render.unknown_google(who.email,
                                                 self._open_signup()), 403
                self._redirect(pending.next, [
                    self._cookie(door.registry.sign(reader, until),
                                 _SESSION_SECONDS), spent])
                return "", 0
            if pending.purpose == "signup":
                try:
                    from db.migrate import prepare           # noqa: PLC0415
                    prepare(pending.language)
                    reader = door.registry.join_with_google(
                        pending.name, who.subject, who.email, pending.language,
                        pending.native, pending.invite)
                except SystemExit as refused:
                    back = (f"/signup?invite={quote(pending.invite)}"
                            if pending.invite else "/signup")
                    return render.google_failed(
                        str(refused).capitalize() + ".", back), 400
                self._redirect("/", [
                    self._cookie(door.registry.sign(reader, until),
                                 _SESSION_SECONDS), spent])
                return "", 0
            current = self._reader() if door.shared else None
            if current is None or current.name != pending.name:
                return render.google_failed(
                    "Sign in first, then link a Google account in Settings.",
                    "/login"), 403
            try:
                door.registry.link_google(current.name, who.subject, who.email)
            except SystemExit:
                self._redirect("/settings?account=google-taken", spent)
                return "", 0
            # Linking changes what a session is signed over: this device
            # gets a new one, every other is signed out.
            renewed = door.registry.get(current.name)
            self._redirect("/settings?account=google", [
                self._cookie(door.registry.sign(renewed, until),
                             _SESSION_SECONDS), spent])
            return "", 0

        def _google_unlink(self, reader) -> None:
            if reader is None:
                self._redirect("/settings")
                return
            try:
                door.registry.unlink_google(reader.name)
            except SystemExit:
                self._redirect("/settings?account=needs-password")
                return
            renewed = door.registry.get(reader.name)
            value = door.registry.sign(renewed, int(time.time()) + _SESSION_SECONDS)
            self._redirect("/settings?account=unlinked",
                           self._cookie(value, _SESSION_SECONDS))

        def _google_cookie(self, value: str, seconds: int) -> str:
            secure = "; Secure" if door.google and door.google.secure else ""
            return (f"{_GOOGLE_COOKIE}={value}; Max-Age={seconds}; "
                    f"Path={_GOOGLE_PATH}; HttpOnly; SameSite=Lax{secure}")

        def _cookie_named(self, name: str) -> str:
            try:
                jar = SimpleCookie(self.headers.get("Cookie", ""))
            except CookieError:
                return ""
            morsel = jar.get(name)
            return morsel.value if morsel else ""

        def _host(self) -> str:
            """The host the browser asked for, through a proxy or not."""
            return (self.headers.get("X-Forwarded-Host")
                    or self.headers.get("Host") or "")

        def _cookie(self, value: str, seconds: int) -> str:
            # `Secure` when the browser's side of the proxy was HTTPS: this
            # process only ever sees plain HTTP from whatever stands in
            # front, and a cookie marked Secure on a plain-HTTP site (a
            # phone on the home wifi) would never come back.
            secure = ("; Secure" if self.headers.get("X-Forwarded-Proto") ==
                      "https" else "")
            return (f"{COOKIE}={value}; Max-Age={seconds}; Path=/; HttpOnly; "
                    f"SameSite=Lax{secure}")

        def _route_open(self, path: str, query: dict) -> tuple[str, int]:
            """What answers without a session."""
            render.ACTIVE.reader = ""
            render.ACTIVE.shared = False
            if path == "/signup":
                token = query.get("invite") or ""
                if token:
                    found = door.registry.invitation(token)
                    if found is None:
                        return render.invitation_gone(), 410
                    return render.signup_page("", token, found,
                                              google=door.google is not None), 200
                if door.google is None:
                    return render.no_invitation(), 403
                if not self._open_signup():
                    return render.signup_closed(), 403
                return render.open_signup_page(""), 200
            if path == "/auth/google/callback":
                return self._google_back(query)
            if path == "/login":
                if not door.shared:
                    return self._redirect("/"), 0
                if self._reader() is not None:
                    return self._redirect(query.get("next") or "/"), 0
                return render.login_page("", _local(query.get("next") or "/"),
                                         google=door.google is not None), 200
            # Safari asks for both of these unprompted the moment you add the
            # page to a home screen. They used to fall through and come back
            # as an HTML 404 with a 200-shaped body.
            if path in ("/favicon.ico", "/apple-touch-icon.png",
                        "/apple-touch-icon-precomposed.png"):
                return self._send_static("/static/icon-512.png"), 0
            if path == "/manifest.webmanifest":
                return self._send_static("/static/manifest.webmanifest"), 0
            return self._send_static(path), 0

        def _route(self, path: str, query: dict, viewers) -> tuple[str, int]:
            viewer = viewers.pick(query)
            if path == "/":
                return viewer.next_up(query), 200
            if path == "/roadmap":
                return viewer.roadmap(query), 200
            if path == "/fix":
                return viewer.fix(query), 200
            if path == "/subtitles":
                return viewer.subtitles(query), 200
            if path == "/settings":
                return viewer.settings(query), 200
            if path == "/frontier":
                return viewer.frontier(query), 200
            if path in ("/anki.csv", "/anki-english.csv"):
                plain = path == "/anki.csv"
                self._send_file(
                    viewer.anki_csv(query, english=not plain), "text/csv",
                    "anki-cards.csv" if plain else "anki-cards-english.csv")
                return None, 0
            if path == "/words":
                return viewer.word_search(query), 200
            if path == "/anki":
                return viewer.anki_page(query), 200
            if path == "/hear":
                return viewer.hear(query), 200
            if path == "/starred":
                return viewer.starred(query), 200
            if path == "/plan":
                return viewer.plan(query), 200
            if path == "/video":
                return viewer.video_page(query), 200
            if path == "/channels":
                return viewer.channels(query), 200
            if path == "/reels":
                return viewer.reels(query), 200
            if path == "/lists":
                return viewer.word_lists(query), 200
            if path == "/cover":
                return viewer.cover_page(query), 200
            if path == "/blocked":
                return viewer.blocked(query), 200
            if path == "/quiz":
                return viewer.quiz(query), 200
            if path == "/watch":
                return viewer.watch(query), 200
            if path == "/study":
                return viewer.study(query), 200
            if path == "/mine":
                return viewer.mine(query), 200
            if path == "/review":
                return viewer.review(query), 200
            if path == "/journey":
                return viewer.journey_page(query), 200
            if path == "/api/journey":
                self._send_json(viewer.journey_json(query))
                return "", 0
            if path == "/api/cover-search":
                self._send_json(viewer.cover_search_json(query))
                return "", 0
            if path == "/api/next":
                self._send_json(viewer.next_json(query))
                return "", 0
            if path == "/api/study":
                self._send_json(viewer.study_json(query))
                return "", 0
            if path == "/api/reels":
                self._send_json(viewer.reels_json(query))
                return "", 0
            if path == "/api/quiz":
                self._send_json(viewer.quiz_json(query))
                return "", 0
            if path == "/api/transcript":
                self._send_json(viewer.transcript_json(query.get("video", "")))
                return "", 0
            if path == "/api/gloss":
                self._send_json(viewer.gloss_json(query))
                return "", 0
            if path.startswith("/unit/"):
                _, _, kind, key = path.split("/", 3)
                return viewer.unit(kind, unquote(key), query), 200
            return _missing(path), 404

        def _send_static(self, path: str) -> str:
            """A file from `web/static`, and nothing outside it.

            The check is on the *resolved* path rather than the requested one,
            because `..` and symlinks are the two ways a string that looks
            local stops being local.
            """
            root = Path(__file__).resolve().parent / "static"
            target = (root / path[len("/static/"):]).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                self._send(_missing(path), status=404)
                return ""
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", TYPES.get(target.suffix,
                                                       "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            # Long, because these are the only things here that never change
            # without also changing name — and a phone on cellular should not
            # re-fetch an icon.
            self.send_header("Cache-Control", "public, max-age=31536000")
            self.end_headers()
            self.wfile.write(body)
            return ""

        def _send_json(self, data, status: int = 200) -> None:
            import json
            payload = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_file(self, body: str, kind: str, name: str) -> None:
            """A download rather than a page. `_send` says text/html, which a
            browser renders instead of saving."""
            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Disposition",
                             f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send(self, html: str, status: int = 200) -> None:
            payload = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def _local(target: str) -> str:
    """`target` if it is a path on this site, else the front page.

    `//elsewhere.example` and `/\\elsewhere.example` both start with a slash
    and are both read by browsers as another host.
    """
    if (not target.startswith("/") or target.startswith("//")
            or "\\" in target):
        return "/"
    return target


def _signed_out() -> str:
    from web.render import layout
    return layout("Signed out", "<h1>Signed out</h1><p class='sub'>"
                  "<a href='/login'>Sign in</a> and try again.</p>")


def _report(error: Exception, path: str) -> None:
    """Put the whole traceback on the terminal.

    The page shows a trimmed one so it stays readable; the terminal gets all
    of it, because that is what gets copied into a bug report.
    """
    import traceback
    print(f"\n--- error serving {path} ---", flush=True)
    traceback.print_exception(error)


def _missing(path: str) -> str:
    from html import escape
    from web.render import layout
    return layout("Not found",
                  f"<h1>Not found</h1><p class='sub'><code>{escape(path)}</code></p>")


def _oops(error: Exception) -> str:
    """Show the failure rather than a blank page — this is a local tool."""
    import traceback
    from html import escape
    from web.render import layout
    detail = escape("".join(traceback.format_exception(error))[-2000:])
    return layout("Error", f"<h1>Something broke</h1><pre>{detail}</pre>")
