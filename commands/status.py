"""`status` — what has been built and what is due."""
from __future__ import annotations

from datetime import datetime

from roadmap import RoadmapStore


class StatusCommand:
    def run(self, app) -> None:
        settings = app.settings
        builds = app.corpus_store.builds()
        print("corpus builds:")
        for name, count in sorted(builds.items()):
            print(f"  {name:<12} {count:>7} sentences")
        if not builds:
            print("  (none — run `build-corpus tatoeba`)")

        steps = RoadmapStore(settings.state_path).count()
        total, due = app.card_store.counts(datetime.now())
        print(f"roadmap: {steps} steps")
        print(f"cards:   {total} scheduled, {due} due now")

        for path in (settings.known_words, settings.function_words):
            mark = "ok" if path.exists() else "MISSING"
            print(f"vocab:   {path.name:<22} {mark}")
