"""`serve` — a web page for looking at the results, for one reader or several."""
from __future__ import annotations

from web import LocalServer


class ServeCommand:
    def run(self, app, port: int = 8765, open_browser: bool = True,
            host: str = "127.0.0.1") -> None:
        from readers import Registry                     # noqa: PLC0415
        registry = Registry()
        if not registry.shared:
            self._warm(app, refuse=True)
            LocalServer(app, port, host).serve(open_browser)
            return

        # The owner and the readers they let in warmed before the socket
        # opens, for the same reason the single reader always was -- see
        # `_warm`. One reader's trouble is reported and does not keep the
        # other's pages from being served: a reader whose language has no
        # corpus yet still has to be able to sign in and see that it has
        # none. Readers who signed up on their own are made on their first
        # page instead: there may be many, and each holds a corpus of its
        # own -- 2.1 GB measured for German (`web.limits`).
        from config import Settings                      # noqa: PLC0415
        from context import Application                  # noqa: PLC0415
        apps = {}
        for reader in registry.readers().values():
            if not (reader.password or reader.google):
                print(f"{reader.name}: no password yet, so cannot sign in — "
                      f"`python main.py reader password {reader.name}`",
                      flush=True)
                continue
            if reader.joined == "google":
                continue
            mine = (app if reader.name == app.settings.reader
                    else Application(Settings.for_reader(reader)))
            print(f"{reader.name}:", flush=True)
            try:
                self._warm(mine, refuse=False)
            except (Exception, SystemExit) as error:   # noqa: BLE001 — go on
                print(f"  not ready: {error}", flush=True)
            apps[reader.name] = mine
        LocalServer(app, port, host, apps=apps).serve(open_browser)

    @staticmethod
    def _warm(app, refuse: bool) -> None:
        builds = app.corpus_store.builds(teachable_only=True)
        if not builds:
            whose = (f" --reader {app.settings.reader}"
                     if app.settings.reader else "")
            message = f"nothing built yet — run `build-corpus subtitle{whose}` first"
            if refuse:
                raise SystemExit(message)
            print(f"  {message}", flush=True)
            return

        # Warm up before opening the socket. This is where the setup-dependent
        # failures live — a stopped database, a missing spaCy model — and doing
        # it here means they arrive as a plain message on the terminal rather
        # than a traceback inside the first page.
        #
        # It is nearly free when `resolved.json` still holds a valid entry,
        # and only then costs the parser and the database when it does not.
        # So it is a canary rather than a cost: what it really proves is that
        # the resolved cache is present and current.
        #
        # The value is deliberately discarded. `Viewer` is built separately
        # and resolves the known set again on its first render, which is a
        # dictionary read once this has passed.
        print("loading vocabulary and parser…", flush=True)
        try:
            known = app.known_set()
        except Exception as error:              # noqa: BLE001 — report and stop
            raise SystemExit(
                f"could not resolve the vocabulary: {type(error).__name__}: {error}\n"
                f"The database must be running and the spaCy model for "
                f"{app.settings.language!r} installed — see the setup notes "
                "in README.md."
            ) from error
        print(f"  {len(known):,} units known, "
              f"{sum(builds.values()):,} sentences cached", flush=True)
