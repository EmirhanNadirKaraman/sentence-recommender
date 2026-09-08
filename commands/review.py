"""`review` — a terminal SRS session over the cards that are due."""
from __future__ import annotations

from datetime import datetime

from srs import ReviewSession


class ReviewCommand:
    def run(self, app, limit: int = 20,
            builds: tuple[str, ...] = ()) -> None:
        now = datetime.now()
        total, due = app.card_store.counts(now)
        if not due:
            print(f"Nothing due. {total} cards scheduled.")
            return

        print(f"{due} of {total} cards due.  Enter to skip, 'skip' to skip.")
        session = ReviewSession(
            app.card_store, app.scheduler, app.prompts(*builds)
        )
        report = session.run(app.known_set().units, limit=limit, now=now)
        print(f"\n{report.summary()}")
        if report.missed:
            print("  missed: " + ", ".join(u.key for u in report.missed))
