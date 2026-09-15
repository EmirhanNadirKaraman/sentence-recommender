"""`export-deck` — the teaching order as a PDF and a slideshow.

The plan lives in the state database and is read through a web page. That is
the right home for it while you are working, and the wrong one on a train, on
paper, or on a projector. This writes the same steps out as files that do not
need the app running.

Both formats come from one list of cards, so they cannot disagree about what
step 412 says. See `deck` for why that matters and `deck.speech` for the
audio, which is named from the same cards.
"""
from __future__ import annotations

from pathlib import Path

import os

from deck import cards_from
from deck.gloss import GlossStore
from roadmap.store import RoadmapStore

# The strict plan aimed at the study list: the one whose every step is i+1
# with every word in the sentence counted. The looser plans are exportable by
# name, but this is the one worth printing.
DEFAULT_LABEL = "generated+subtitle+transcript:good:strict:goals"


class ExportDeckCommand:
    def run(self, app, out_dir: Path, label: str = DEFAULT_LABEL,
            formats: tuple[str, ...] = ("pdf", "pptx"),
            limit: int | None = None, examples: int = 3) -> None:
        store = RoadmapStore(app.settings.state_path)
        steps = store.load(label, limit=limit)
        if not steps:
            known = store.labels()
            raise SystemExit(
                f"no plan stored as {label!r}\n  stored plans:\n    "
                + "\n    ".join(known or ["(none — run `build-roadmap`)"]))

        stamp = store.stamp(label)
        if stamp and stamp != _current():
            # Said, not refused. An old plan is still a perfectly good
            # document; it just no longer matches the corpus, and a reader
            # who prints it should know that before they wonder why a
            # sentence is missing from the app.
            print("warning: this plan was built under different rules — "
                  "rebuild it with `build-roadmap` for a current deck")

        # Decks and glosses, not just the steps. Left out, this rendered one
        # sentence per card and only the handful of translations the corpus
        # carried of its own -- 85 of 3,902 -- which looks like a finished
        # document and is a third of one.
        decks = store.decks(label, steps, limit=examples)
        glosses = GlossStore(app.settings.state_path)
        said = os.environ.get("LLM_MODEL", "")
        cards = cards_from(steps, decks, glosses.senses(said),
                           glosses.sentences(said))
        sentences = sum(len(c.examples) for c in cards)
        glossed = sum(1 for c in cards if c.glossed)
        relaxed = sum(1 for c in cards if c.beside)
        print(f"{len(cards):,} steps · {sentences:,} sentences · "
              f"{glossed:,} glossed"
              + (f" · {relaxed:,} taught two words at once" if relaxed else ""))
        if glossed < len(cards):
            print(f"  {len(cards) - glossed:,} have no English yet and are "
                  "marked in the document; `gloss-deck` fills them in")

        # Imported here rather than at the top: reportlab and python-pptx
        # are wanted by this one command, and every other command would pay
        # for them at start-up.
        from deck.pdf import write_pdf        # noqa: PLC0415
        from deck.slides import write_pptx    # noqa: PLC0415

        out_dir.mkdir(parents=True, exist_ok=True)
        stem = label.replace(":", "_").replace("+", "-")
        for kind in formats:
            path = out_dir / f"{stem}.{kind}"
            writer = write_pdf if kind == "pdf" else write_pptx
            print(f"  writing {path} …", flush=True)
            writer(cards, path, label, stamp)
            print(f"  {path}  {path.stat().st_size / 1e6:.1f} MB")


def _current() -> str:
    from roadmap.store import current_stamp    # noqa: PLC0415
    return current_stamp()
