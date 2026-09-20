"""`build-study-list` — merge the ranking and the form dictionary into one list."""
from __future__ import annotations

from vocab.study_list import StudyListBuilder


class BuildStudyListCommand:
    def run(self, app, force: bool = False) -> None:
        settings = app.settings
        for path in (settings.order_words, settings.form_words):
            if not path.exists():
                raise SystemExit(f"missing {path}")

        builder = StudyListBuilder(settings.order_words, settings.form_words)
        ranked, rest = builder.write(settings.goal_words, force=force)

        print(f"wrote {settings.goal_words}")
        print(f"  {ranked:,} ranked, from {settings.order_words.name}")
        print(f"  {rest:,} more known to {settings.form_words.name} but never ranked")
        print("\nRebuild the roadmap to use it:")
        print("  python main.py build-roadmap --source subtitle --goals")
