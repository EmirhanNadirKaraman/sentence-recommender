"""`progress` — how much of the deck is done, and how much is left.

And of the corpus: `translate-sentences` runs for days, and the same
question -- how far, from what is stored rather than from what a log said --
is answered here for it too.

Written because the question kept being asked and kept being answered badly.
A long run's own log says where it has got to, which is not the same thing:
`gloss-deck` prints the position of the card it is glossing, so watching it
reach 3,716 tells you how far through the deck it is walking, not how much
work remains -- and a stage that pipes its output through `tail` hides even
the total it printed at startup.

Every count here is derived from what is stored rather than from what a log
said, so it is right whether a stage is running, finished, or has not begun.
"""
from __future__ import annotations

import os


class ProgressCommand:
    def run(self, app, label: str | None = None) -> None:
        from commands.export_deck import DEFAULT_LABEL     # noqa: PLC0415
        from corpus.fixes import FixStore                  # noqa: PLC0415
        from deck import cards_from                        # noqa: PLC0415
        from deck.gloss import GlossStore, missing         # noqa: PLC0415
        from deck.pieces import PieceStore, key_for        # noqa: PLC0415
        from deck.speech import (DEFAULT_ENGLISH, DEFAULT_GERMAN,
                                 lines_for)                # noqa: PLC0415
        from roadmap.store import RoadmapStore             # noqa: PLC0415

        label = label or DEFAULT_LABEL
        settings = app.settings
        store = RoadmapStore(settings.state_path)
        steps = store.load(label)
        if not steps:
            raise SystemExit(f"no plan stored as {label!r}")
        decks = store.decks(label, steps, limit=3)
        glosses = GlossStore(settings.state_path)
        model = os.environ.get("LLM_MODEL", "")
        english = glosses.sentences(model)
        # Two views of the same deck, because two consumers build it two ways
        # and reporting one number for both was wrong. `gloss-deck` works on
        # the sentence as the corpus holds it, since that is what its store is
        # keyed by; `speak-deck` works on the repaired text, since that is
        # what a card shows. Asked with the wrong one, this reported 60 cards
        # owed a translation where the gloss would ask about 6.
        plain = cards_from(steps, decks, glosses.senses(model), english)
        cards = cards_from(steps, decks, glosses.senses(model), english,
                           FixStore(settings.state_path).all())

        print(f"{label}\n  {len(cards):,} cards\n")

        shown = [e.text for card in plain for e in card.examples]
        done = [t for t in shown if english.get(t, "").strip()]
        owed = missing(plain, glosses.asked(model))
        print("translations")
        print(f"  {len(done):>7,} of {len(shown):,} sentences "
              f"({len(done) / max(len(shown), 1):.1%})")
        print(f"  {len(owed):>7,} cards still to ask")

        # The whole corpus, not the deck: what `translate-sentences` walks.
        # Counted against the sentences that arrived without English, since
        # the ones that came with it are not anyone's work to do.
        wanted = app.corpus_store.untranslated()
        have = sum(1 for text, _ in wanted if english.get(text, "").strip())
        asked = sum(1 for text, _ in wanted if text in english)
        print("\ncorpus translations")
        print(f"  {have:>7,} of {len(wanted):,} sentences "
              f"({have / max(len(wanted), 1):.1%})")
        print(f"  {len(wanted) - asked:>7,} still to ask")

        # Only cards with a gloss are recorded, so the denominator matches
        # what `speak-deck` will actually try to say.
        pieces = PieceStore(settings.state_path)
        have = set(pieces.have())
        needed = {
            key_for(text, DEFAULT_GERMAN if german else DEFAULT_ENGLISH, slow)
            for card in cards if card.glossed
            for text, german, slow, _gap, _role in lines_for(card)
            if text.strip()}
        print("\nrecordings")
        print(f"  {len(needed & have):>7,} of {len(needed):,} lines "
              f"({len(needed & have) / max(len(needed), 1):.1%})")
        print(f"  {len(needed - have):>7,} still to record")

        recipes = pieces.card_recipes()
        stale = [card for card in cards
                 if recipes.get(card.stem) != "|".join(
                     f"{key_for(t, DEFAULT_GERMAN if de else DEFAULT_ENGLISH, sl)}"
                     f":{gap:.2f}"
                     for t, de, sl, gap, _r in lines_for(card))]
        print("\nmerged cards")
        print(f"  {len(cards) - len(stale):>7,} of {len(cards):,} current")
        print(f"  {len(stale):>7,} to re-merge")
