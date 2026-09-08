"""A local, single-user web viewer.

Built on `http.server` rather than a framework: the site is six routes and a
form, and a dependency that has to be installed before the results can be
looked at is a worse trade than forty lines of routing.

Bound to 127.0.0.1 only. There is no authentication, and the pages read
whatever the local database holds, so it must not be exposed beyond this
machine.
"""
from __future__ import annotations

import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from web.handlers import Viewer

HOST = "127.0.0.1"


class LocalServer:
    """Routes requests to `Viewer` and serves the HTML it returns."""

    def __init__(self, app, port: int = 8765) -> None:
        self._viewer = Viewer(app)
        self._port = port

    def serve(self, open_browser: bool = True) -> None:
        viewer = self._viewer
        handler = _make_handler(viewer)
        server = ThreadingHTTPServer((HOST, self._port), handler)
        url = f"http://{HOST}:{self._port}/"
        print(f"serving {url}  (ctrl-c to stop)")
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            server.server_close()


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
            if path == "/blocked":
                return viewer.blocked(query), 200
            if path == "/watch":
                return viewer.watch(query), 200
            if path == "/api/transcript":
                self._send_json(viewer.transcript_json(query.get("video", "")))
                return "", 0
            if path.startswith("/unit/"):
                _, _, kind, key = path.split("/", 3)
                return viewer.unit(kind, unquote(key), query), 200
            return _missing(path), 404

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
