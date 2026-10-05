"""`build-study-list` — merge the ranking and the form dictionary into one list."""
from __future__ import annotations

from vocab.study_list import StudyListBuilder


class BuildStudyListCommand:
    def run(self, app, force: bool = False) -> None:
        settings = app.settings
        if settings.order_words is None or settings.form_words is None:
            # The merge exists because German's ranking and its valency
            # dictionary are two files. A list in any other language is
            # already the study list as it stands.
            raise SystemExit(
                "build-study-list merges the German ranking with the German "
                "valency dictionary. For any other language the word list is "
                f"the study list: put it at {settings.goal_words}, one word "
                "or expression per line.")
        for path in (settings.order_words, settings.form_words):
            if not path.exists():
                raise SystemExit(f"missing {path}")

        builder = StudyListBuilder(settings.order_words, settings.form_words,
                                   settings.expressions)
        ranked, rest = builder.write(settings.goal_words, force=force)

        print(f"wrote {settings.goal_words}")
        print(f"  {ranked:,} ranked, from {settings.order_words.name}")
        print(f"  {len(builder.expressions()):,} fixed expressions, from "
              f"{settings.expressions.name}")
        print(f"  {rest:,} more known to {settings.form_words.name} but never ranked")
        print("\nRebuild the roadmap to use it:")
        print("  python main.py build-roadmap --source subtitle --goals")
