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
            print("  (none — run `build-corpus subtitle`)")

        roadmaps = RoadmapStore(settings.state_path).sources()
        total, due = app.card_store.counts(datetime.now())
        print("roadmaps:")
        for name, count in sorted(roadmaps.items()):
            print(f"  {name:<12} {count:>7} steps")
        if not roadmaps:
            print("  (none — run `build-roadmap`)")
        print(f"cards:   {total} scheduled, {due} due now")

        for path in (settings.known_words, settings.function_words):
            mark = "ok" if path.exists() else "MISSING"
            print(f"vocab:   {path.name:<22} {mark}")
