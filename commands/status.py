"""`status` — what has been built and what is due."""
from __future__ import annotations

from datetime import datetime

from roadmap import RoadmapStore


class StatusCommand:
    def gather(self, app) -> dict:
        """The report as data: which builds and roadmaps exist and how big
        they are, the card counts, and whether the vocabulary files are
        there. `run` prints it; the MCP server returns it as it is."""
        settings = app.settings
        total, due = app.card_store.counts(datetime.now())
        return {
            "corpus": dict(app.corpus_store.builds()),
            "roadmaps": dict(RoadmapStore(settings.state_path).sources()),
            "cards": {"scheduled": total, "due": due},
            "vocab": {path.name: path.exists()
                      for path in (settings.known_words,
                                   settings.function_words)},
        }

    def run(self, app) -> None:
        report = self.gather(app)
        print("corpus builds:")
        for name, count in sorted(report["corpus"].items()):
            print(f"  {name:<12} {count:>7} sentences")
        if not report["corpus"]:
            print("  (none — run `build-corpus subtitle`)")

        print("roadmaps:")
        for name, count in sorted(report["roadmaps"].items()):
            print(f"  {name:<12} {count:>7} steps")
        if not report["roadmaps"]:
            print("  (none — run `build-roadmap`)")
        cards = report["cards"]
        print(f"cards:   {cards['scheduled']} scheduled, {cards['due']} due now")

        for name, present in report["vocab"].items():
            mark = "ok" if present else "MISSING"
            print(f"vocab:   {name:<22} {mark}")
