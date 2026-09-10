"""A local, single-user web viewer.

Built on `http.server` rather than a framework: the site is six routes and a
form, and a dependency that has to be installed before the results can be
looked at is a worse trade than forty lines of routing.

Loopback by default. There is still no authentication of any kind, and the
pages read and write whatever the local database holds — so binding it
anywhere else puts that on the network for anyone who can reach the port.
`serve --host` exists for reaching it from a phone on the same wifi, and says
so out loud when it is used; anything beyond that wants a real front door
(see IOS.md).
"""
from __future__ import annotations

import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from web.handlers import Viewer

LOOPBACK = "127.0.0.1"

TYPES = {
    ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/png",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".woff2": "font/woff2", ".json": "application/json; charset=utf-8",
}


class LocalServer:
    """Routes requests to `Viewer` and serves the HTML it returns."""

    def __init__(self, app, port: int = 8765, host: str = LOOPBACK) -> None:
        self._viewer = Viewer(app)
        self._port = port
        self._host = host

    def serve(self, open_browser: bool = True) -> None:
        viewer = self._viewer
        handler = _make_handler(viewer)
        server = ThreadingHTTPServer((self._host, self._port), handler)
        url = f"http://{self._reachable_at()}:{self._port}/"
        # Flushed, both of them. Redirected output is block-buffered, so the
        # one line whose entire job is telling you what to type into the other
        # device is the one that vanishes under nohup, ssh or a service
        # manager — which is exactly where it is needed.
        print(f"serving {url}  (ctrl-c to stop)", flush=True)
        if self._host != LOOPBACK:
            print("  no authentication — anyone who can reach this port can "
                  "read your corpus and mark words known", flush=True)
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
        """
        if self._host == LOOPBACK:
            return self._host
        if self._host not in ("0.0.0.0", "::", ""):
            return self._host
        name = socket.gethostname()
        return name if name.endswith(".local") else f"{name}.local"


def _make_handler(viewer: Viewer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

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
                html, status = self._route(path, query)
                if status:                     # 0 means the route already replied
                    self._send(html, status)
            except Exception as error:            # noqa: BLE001 — show it, don't die
                _report(error, self.path)
                self._send(_oops(error), status=500)

        def do_POST(self) -> None:                # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8")
            # Joined rather than truncated: a set of checkboxes posts one name
            # many times, and keeping only the first silently drops the rest.
            form = {k: "\x00".join(v) for k, v in parse_qs(body).items()}
            posted = urlparse(self.path).path.rstrip("/")
            try:
                if posted == "/known":
                    self._redirect(viewer.mark_known(form))
                elif posted == "/add-video":
                    self._redirect(viewer.add_video(form))
                elif posted == "/add-channel":
                    self._redirect(viewer.add_channel(form))
                elif posted == "/quiz":
                    self._redirect(viewer.answer_quiz(form))
                elif posted == "/hide":
                    self._redirect(viewer.hide_sentence(form))
                elif posted == "/fix":
                    self._redirect(viewer.save_fix(form))
                else:
                    self._send(_missing(self.path), status=404)
            except Exception as error:            # noqa: BLE001
                _report(error, self.path)
                self._send(_oops(error), status=500)

        def _redirect(self, target: str) -> None:
            """303 after a state change, so a refresh does not repeat it."""
            self.send_response(303)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _route(self, path: str, query: dict) -> tuple[str, int]:
            if path == "/":
                return viewer.next_up(query), 200
            if path == "/roadmap":
                return viewer.roadmap(query), 200
            if path == "/fix":
                return viewer.fix(query), 200
            if path == "/subtitles":
                return viewer.subtitles(query), 200
            if path == "/reels":
                return viewer.reels(query), 200
            if path == "/blocked":
                return viewer.blocked(query), 200
            if path == "/quiz":
                return viewer.quiz(query), 200
            if path == "/watch":
                return viewer.watch(query), 200
            if path == "/api/next":
                self._send_json(viewer.next_json(query))
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
            if path.startswith("/unit/"):
                _, _, kind, key = path.split("/", 3)
                return viewer.unit(kind, unquote(key), query), 200
            # Safari asks for both of these unprompted the moment you add the
            # page to a home screen. They used to fall through and come back
            # as an HTML 404 with a 200-shaped body.
            if path in ("/favicon.ico", "/apple-touch-icon.png",
                        "/apple-touch-icon-precomposed.png"):
                return self._send_static("/static/icon-512.png"), 0
            if path == "/manifest.webmanifest":
                return self._send_static("/static/manifest.webmanifest"), 0
            if path.startswith("/static/"):
                return self._send_static(path), 0
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

        def _send_json(self, data) -> None:
            import json
            payload = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
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
