"""`serve` — a local web page for looking at the results."""
from __future__ import annotations

from web import LocalServer


class ServeCommand:
    def run(self, app, port: int = 8765, open_browser: bool = True) -> None:
        builds = app.corpus_store.builds(teachable_only=True)
        if not builds:
            raise SystemExit("nothing built yet — run `build-corpus tatoeba` first")

        # Warm up before opening the socket. Loading the parser and resolving
        # the vocabulary takes seconds and is where the setup-dependent
        # failures live — a stopped database, a missing spaCy model. Doing it
        # here means those arrive as a plain message on the terminal, not as a
        # traceback inside the first page.
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

        LocalServer(app, port).serve(open_browser)
