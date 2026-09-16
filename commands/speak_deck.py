"""`speak-deck` — read the teaching order aloud, locally.

One WAV per card, read in the order the card is written: the word, then each
sentence with its English and what the word means there. Two voices, because
a card is half German and half English — see `deck.speech`.

A tab-separated manifest goes beside the audio, which is what turns a folder
of WAVs into something a player or an SRS can use.

Resumable, because it is a long job: run it again and it does the files that
are not there yet.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from commands.export_deck import DEFAULT_LABEL
from corpus.fixes import FixStore
from deck import cards_from
from deck.gloss import GlossStore
from deck.pieces import PieceStore
from deck.speech import (DEFAULT_ENGLISH, DEFAULT_GERMAN, DEFAULT_HF_MODEL,
                         PiperSpeaker, TransformersSpeaker, speak,
                         synthesise, write_manifest)
from roadmap.store import RoadmapStore


class SpeakDeckCommand:
    @staticmethod
    def _report(started: float):
        """Exact counts and a rate, because this runs for a long time.

        A rate rather than an estimate: how long it has left depends on
        sentences it has not read yet, and a countdown that keeps revising
        itself is worth less than the number it is computed from.
        """
        def say(done: int, total: int, written: int) -> None:
            rate = done / max(time.perf_counter() - started, 1e-9)
            print(f"  … {done:>5,} / {total:,} · {written:,} written · "
                  f"{rate:.1f}/s", flush=True)
        return say

    def run(self, app, out_dir: Path, label: str = DEFAULT_LABEL,
            engine: str = "piper", german: str = DEFAULT_GERMAN,
            english: str = DEFAULT_ENGLISH, model: str = DEFAULT_HF_MODEL,
            device: str | None = None, limit: int | None = None,
            overwrite: bool = False, cuda: bool = False,
            slow: bool = False, examples: int = 3,
            german_only: bool = False,
            log: Path = Path("out/speak.log")) -> None:
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

        waiting = sum(1 for card in cards if not card.glossed)
        if waiting:
            # Left for a later run rather than read in German only, so this
            # can go beside `gloss-deck` rather than after it.
            print(f"{waiting:,} of {len(cards):,} cards have no English yet "
                  "and will be left for a later run"
                  + (" — reading them in German only as asked"
                     if german_only else ""))

        voices = settings.data_dir / "voices"
        if engine == "piper":
            de = PiperSpeaker(german, voices, use_cuda=cuda)
            en = PiperSpeaker(english, voices, use_cuda=cuda)
        else:
            de = TransformersSpeaker(model, device)
            en = TransformersSpeaker(model, device)
        print(f"{len(cards):,} cards · {de.name} + {en.name} · "
              f"{de.sample_rate:,} Hz", flush=True)

        log.parent.mkdir(parents=True, exist_ok=True)

        def note(card, _written: bool) -> None:
            """What it is reading, not just how many. See `deck.speech`."""
            with open(log, "a", encoding="utf-8") as handle:
                handle.write(f"{card.position:>5}  {card.spoken}\n")

        started = time.perf_counter()

        # Two phases, and the split is the point. The first records every
        # distinct line the deck says, once, named by what it says; the
        # second lays those end to end into a card. Only the first costs a
        # voice, and it is the one a rebuild almost never has work for --
        # reordering the plan changes which lines go together, not what the
        # lines are.
        pieces = PieceStore(settings.state_path)
        # Two folders under one root: the lines as recorded, and the cards
        # assembled from them. Kept apart because they are different things
        # to look through -- 31,802 pieces named by a hash, against 3,902
        # cards named by the word they teach -- and a folder holding both at
        # once is navigable as neither.
        piece_dir = out_dir / "pieces"
        card_dir = out_dir / "cards"
        card_dir.mkdir(parents=True, exist_ok=True)
        speakable = [c for c in cards if c.glossed or german_only]
        fresh, already = synthesise(
            speakable, de, en, pieces, piece_dir, slow=slow,
            on_progress=lambda n, total: print(
                f"  … {n:,} of {total:,} lines recorded", flush=True))
        print(f"  {fresh:,} lines recorded · {already:,} already had one · "
              f"{pieces.count():,} in the store", flush=True)

        written, skipped, waiting_now = speak(
            cards, de, en, card_dir, overwrite=overwrite, slow=slow,
            on_progress=self._report(started), require_gloss=not german_only,
            on_card=note, pieces=pieces.have(), piece_dir=piece_dir)
        manifest = write_manifest(cards, card_dir / "deck.tsv")

        spent = time.perf_counter() - started
        size = sum(p.stat().st_size for p in card_dir.glob("*.wav"))
        print(f"\n{written:,} written, {skipped:,} already there, "
              f"{waiting_now:,} still waiting on English, in "
              f"{spent / 60:.1f} min")
        if waiting_now:
            print(f"  run it again when `gloss-deck` has caught up; the "
                  f"{written + skipped:,} already read are not read twice")
        print(f"  {out_dir}  {size / 1e6:,.0f} MB of audio")
        print(f"  {log}  — the running log")
        print(f"  {manifest}  — position, word, sentence, translation, "
              "meaning, audio")
