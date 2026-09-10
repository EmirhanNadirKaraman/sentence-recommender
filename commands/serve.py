"""`serve` — a local web page for looking at the results."""
from __future__ import annotations

from web import LocalServer


class ServeCommand:
    def run(self, app, port: int = 8765, open_browser: bool = True,
            host: str = "127.0.0.1") -> None:
        builds = app.corpus_store.builds(teachable_only=True)
        if not builds:
            raise SystemExit("nothing built yet — run `build-corpus subtitle` first")

        # Warm up before opening the socket. This is where the setup-dependent
        # failures live — a stopped database, a missing spaCy model — and doing
        # it here means they arrive as a plain message on the terminal rather
        # than a traceback inside the first page.
        #
        # It is nearly free when `data/resolved.json` still holds a valid
        # entry, and only then costs the parser and the database when it does
        # not. So it is a canary rather than a cost: what it really proves is
        # that the resolved cache is present and current.
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
                "The database must be running and the German spaCy model "
                "installed — see the setup notes in README.md."
            ) from error
        print(f"  {len(known):,} units known, "
              f"{sum(builds.values()):,} sentences cached", flush=True)

        LocalServer(app, port, host).serve(open_browser)
