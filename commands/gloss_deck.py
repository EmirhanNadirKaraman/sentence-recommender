"""`gloss-deck` — the English half of every card, from a local model.

A card says four things: the German word, a sentence using it, that sentence
in English, and what the word means there. The corpus has the first two. This
writes the other two, one call per word, into the state database -- see
`deck.gloss` for the shape and for why the meaning is asked per sense rather
than per sentence.

Long enough to want watching, so it does three things while it runs: prints a
count, appends every finished card to a text file you can `tail -f`, and
re-renders the PDF every so often. That last one is the point: a bad prompt
is worth finding in the first ten minutes, not in the fourth hour.

Resumable. Every card is written the moment it lands, keyed by the word and
the sentence rather than by the plan, so stopping and starting again costs
nothing and asks nothing twice.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from commands.export_deck import DEFAULT_LABEL
from deck import cards_from
from deck.gloss import GlossStore, missing, run
from generation.client import LLMClient
from roadmap.store import RoadmapStore


class GlossDeckCommand:
    def run(self, app, label: str = DEFAULT_LABEL,
            out: Path = Path("out/deck"), log: Path = Path("out/gloss.log"),
            workers: int = 2, every: int = 50, limit: int | None = None,
            examples: int = 3) -> None:
        settings = app.settings
        client = LLMClient(timeout=300)
        if not client.available:
            raise SystemExit(
                "no local model configured — set LLM_BASE_URL and LLM_MODEL "
                "in .env, then check it with `python main.py check-model`")
        model = os.environ.get("LLM_MODEL", "")

        store = RoadmapStore(settings.state_path)
        steps = store.load(label, limit=limit)
        if not steps:
            raise SystemExit(
                f"no plan stored as {label!r}\n  stored plans:\n    "
                + "\n    ".join(store.labels() or ["(none)"]))
        decks = store.decks(label, steps, limit=examples)
        glosses = GlossStore(settings.state_path)

        def build():
            # No repairs applied here, deliberately. The gloss store is keyed
            # by the sentence as the corpus holds it, so a card carrying
            # repaired text would ask about one string and store under
            # another — and `missing` would then see every repaired sentence
            # as never asked, for ever.
            return cards_from(steps, decks, glosses.senses(model),
                              glosses.sentences(model))

        cards = build()
        # What has been *asked*, not what came back with something. A sentence
        # the model declined has a row with nothing against it and is left
        # alone; one that was never put to it has no row at all and is the
        # whole point of this pass. Asked *here*: `translate-sentences` gives
        # a sentence English without ever asking what the word means in it.
        todo = missing(cards, glosses.asked(model))
        print(f"{len(cards):,} cards · {len(cards) - len(todo):,} already "
              f"done · {len(todo):,} to ask\n  {client.describe()}", flush=True)
        if not todo:
            print("nothing to do")
            return

        log.parent.mkdir(parents=True, exist_ok=True)
        out.mkdir(parents=True, exist_ok=True)
        stem = label.replace(":", "_").replace("+", "-")
        pdf = out / f"{stem}.pdf"
        started = time.perf_counter()
        seen = [0]

        def note(card, result) -> None:
            """Append one card to the log, and snapshot the PDF now and then."""
            with open(log, "a", encoding="utf-8") as handle:
                if result is None:
                    handle.write(f"\n[{card.position:>5}] {card.spoken}\n"
                                 "    FAILED\n")
                else:
                    handle.write(f"\n[{card.position:>5}] {card.spoken}\n")
                    for example, (english, means) in zip(card.examples, result):
                        handle.write(f"    {example.text}\n"
                                     f"    {english}\n"
                                     f"    {means}\n")
            seen[0] += 1
            if seen[0] % every == 0:
                # Rendered from the store rather than from `result`, so the
                # snapshot shows everything done so far and not just this run.
                from deck.pdf import write_pdf          # noqa: PLC0415
                write_pdf(build(), pdf, label)

        def say(index, total, failed) -> None:
            rate = index / max(time.perf_counter() - started, 1e-9)
            left = (total - index) / rate / 3600 if rate else 0
            print(f"  … {index:>5,}/{total:,} · {failed:,} failed · "
                  f"{rate * 3600:,.0f}/h · {left:.1f} h left", flush=True)

        done, failed = run(cards, glosses, client, model,
                           verdicts=app.overrides,
                           workers=workers, on_progress=say, every=10,
                           on_card=note)

        from deck.pdf import write_pdf                  # noqa: PLC0415
        write_pdf(build(), pdf, label)
        spent = time.perf_counter() - started
        print(f"\n{done:,} done, {failed:,} failed in {spent / 60:.1f} min")
        print(f"  {log}   — the running log")
        print(f"  {pdf}   — re-rendered with everything so far")
        if failed:
            print(f"  run it again to retry the {failed:,} that failed; "
                  "nothing already done will be asked twice")
