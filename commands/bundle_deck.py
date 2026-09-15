"""`bundle-deck` — the clips joined into episodes, with chapter timestamps.

One WAV and one chapter list per episode. The chapter list is the format a
YouTube description is parsed for, which is also what a podcast chapter list
wants, so the same file serves either.

Nothing here uploads anything. It writes files.
"""
from __future__ import annotations

import os
from pathlib import Path

from commands.export_deck import DEFAULT_LABEL
from deck import cards_from
from deck.episodes import PER_EPISODE, plan, timestamp, write, write_video
from deck.gloss import GlossStore
from roadmap.store import RoadmapStore


class BundleDeckCommand:
    def run(self, app, audio_dir: Path = Path("out/audio"),
            out_dir: Path = Path("out/episodes"),
            label: str = DEFAULT_LABEL, per: int = PER_EPISODE,
            examples: int = 3, limit: int | None = None,
            video: bool = False,
            stills_dir: Path = Path("out/stills")) -> None:
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
                           glosses.sentences(said))

        episodes = plan(cards, audio_dir, per)
        if not episodes:
            raise SystemExit(
                f"no clips in {audio_dir} — run `speak-deck` first")
        heard = sum(len(e.chapters) for e in episodes)
        total = sum(e.seconds for e in episodes)
        print(f"{heard:,} of {len(cards):,} cards have audio · "
              f"{len(episodes)} episodes of {per} · {total / 3600:.1f} h")
        if heard < len(cards):
            print(f"  {len(cards) - heard:,} have no clip yet and are left "
                  "out; `speak-deck` writes them")

        if video:
            # Drawn once each, before any episode is encoded: a card can
            # appear in only one episode, but drawing them together keeps the
            # slow part in one place and makes a failure obvious early.
            from deck.stills import draw_card          # noqa: PLC0415
            print(f"  drawing {heard:,} stills …", flush=True)
            for at, episode in enumerate(episodes):
                for chapter in episode.chapters:
                    still = stills_dir / f"{chapter.card.stem}.png"
                    if not still.exists():
                        draw_card(chapter.card, still)

        index: list[str] = []
        for episode in episodes:
            audio, chapters = write(episode, audio_dir, out_dir)
            if video:
                clip = write_video(episode, stills_dir, audio, out_dir)
                print(f"  {clip.name}  "
                      f"{clip.stat().st_size / 1e6:,.0f} MB", flush=True)
            first = episode.chapters[0].card
            last = episode.chapters[-1].card
            index.append(
                f"{episode.stem}  {timestamp(episode.seconds):>7}  "
                f"words {first.position}-{last.position}  "
                f"{first.spoken} … {last.spoken}")
            print(f"  {audio.name}  {timestamp(episode.seconds)}  "
                  f"{len(episode.chapters)} chapters", flush=True)

        listing = out_dir / "episodes.txt"
        listing.write_text("\n".join(index) + "\n", encoding="utf-8")
        size = sum(p.stat().st_size for p in out_dir.glob("*.wav"))
        print(f"\n  {out_dir}  {size / 1e9:.1f} GB")
        print(f"  {listing}  — what is in each episode")
        print("  each episode's .txt is its chapter list, ready to paste")
