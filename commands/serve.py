"""`serve` — a local web page for looking at the results."""
from __future__ import annotations

from web import LocalServer


class ServeCommand:
    def run(self, app, port: int = 8765, open_browser: bool = True) -> None:
        builds = app.corpus_store.builds()
        if not builds:
            raise SystemExit("nothing built yet — run `build-corpus tatoeba` first")
        print("loading corpus and vocabulary…", flush=True)
        LocalServer(app, port).serve(open_browser)
