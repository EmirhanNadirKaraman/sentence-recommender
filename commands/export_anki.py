"""`export-anki` — the deck as `.apkg` files, audio included.

`deck.tsv` imports too, but leaves the media to be copied by hand. This
carries it, so a phone is one file and one tap away from the whole roadmap.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from commands.export_deck import DEFAULT_LABEL
from corpus.fixes import FixStore
from deck import cards_from
from deck.pieces import PieceStore
from deck.anki import build
from deck.gloss import GlossStore
from roadmap.store import RoadmapStore


class ExportAnkiCommand:
    def run(self, app, audio_dir: Path = Path("out/audio"),
            out_dir: Path = Path("out/anki"), label: str = DEFAULT_LABEL,
            name: str = "German roadmap", per_package: int = 500,
            bitrate: str = "64k", examples: int = 3,
            limit: int | None = None) -> None:
        settings = app.settings
        store = RoadmapStore(settings.state_path)
        steps = store.load(label, limit=limit)
        if not steps:
            raise SystemExit(
                f"no plan stored as {label!r}\n  stored plans:\n    "
                + "\n    ".join(store.labels() or ["(none)"]))
        decks = store.decks(label, steps, limit=examples)
        glosses = GlossStore(settings.state_path)
        said = os.environ.get("LLM_MODEL", "")
        cards = cards_from(steps, decks, glosses.senses(said),
                           glosses.sentences(said),
                           FixStore(app.settings.state_path).all())

        heard = sum(1 for c in cards
                    if (audio_dir / f"{c.stem}.wav").exists())
        print(f"{len(cards):,} cards · {heard:,} with audio · "
              f"{-(-len(cards) // per_package)} package(s) of {per_package}",
              flush=True)
        if heard < len(cards):
            print(f"  {len(cards) - heard:,} have no clip and will be "
                  "text-only; `speak-deck` writes them")

        started = time.perf_counter()

        def say(done: int, total: int) -> None:
            rate = done / max(time.perf_counter() - started, 1e-9)
            print(f"  … {done:>5,}/{total:,} · {rate:.1f}/s", flush=True)

        # Where each sentence was recorded, so the card can carry a player
        # per line rather than one for the whole thing. `role="de"` because
        # a card plays its German; the English and the meaning are recorded
        # too and are what a different arrangement would reach for.
        store = PieceStore(app.settings.state_path)
        spoken = store.paths_for(
            [e.text for card in cards for e in card.examples], role="de")
        if spoken:
            print(f"  {len(spoken):,} sentences have their own clip", flush=True)
        written = build(cards, audio_dir, out_dir, name, per_package,
                        bitrate, on_progress=say, pieces=spoken)
        size = sum(p.stat().st_size for p in written)
        print(f"\n{len(written)} package(s), {size / 1e6:,.0f} MB total")
        for path in written:
            print(f"  {path}  {path.stat().st_size / 1e6:,.0f} MB")
        print("\n  open each on the phone, or File > Import in the desktop app")
