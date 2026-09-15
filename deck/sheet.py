"""The deck as one text file, so a change to it can be read.

The PDF and the slideshow are 11.5 MB of binary between them, and git keeps
whole copies of a binary rather than deltas — so committing a rebuild costs
11.5 MB whether one card moved or three thousand did, and the diff says
nothing a person can read.

Everything in those files comes from `list[Card]`, and a card is a handful of
short strings. Written as a sheet, a rebuild that changes 5% of the deck is a
5% diff: the words that moved are the lines that moved, and `git log -p` on
this file is a history of what the roadmap decided.

It is also the whole deck without the machinery. The renderers take cards and
nothing else — no Postgres, no corpus, no model — so this file plus this
repository regenerates both documents on a laptop that has none of them. That
is the difference between shipping a deck and shipping the means to rebuild
one.

Tab-separated, like every other sheet here: the sentences are full of commas
and none of them contains a tab.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from deck import Card, Example

# Three, because that is what a card shows. Written flat rather than as one
# repeated column, so a row is a card and a diff is a card — grouping them
# would put three sentences on one line and a one-word change would rewrite
# all of it.
EXAMPLES = 3
COLUMNS = (["position", "word", "spoken", "pattern", "beside"]
           + [f"{field}{n}" for n in range(1, EXAMPLES + 1)
              for field in ("german", "english", "means")])


def write_sheet(cards: Iterable[Card], path: Path) -> Path:
    """Write the deck as one tab-separated row per card."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        out = csv.writer(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        out.writerow(COLUMNS)
        for card in cards:
            row = [card.position, card.word, card.spoken,
                   "pattern" if card.is_pattern else "word", card.beside or ""]
            for at in range(EXAMPLES):
                example = (card.examples[at] if at < len(card.examples)
                           else None)
                row += ["" if example is None else example.text,
                        "" if example is None else (example.translation or ""),
                        "" if example is None else (example.means or "")]
            out.writerow(row)
    return path


def read_sheet(path: Path) -> list[Card]:
    """The deck back out of the sheet, ready for either renderer.

    `spoken` is read rather than recomputed. It is derived from the word by
    `deck.spoken`, and deriving it again here would mean a sheet written
    today rendering differently tomorrow if that rule changed — which is
    exactly the drift a file like this exists to prevent. What is in the file
    is what gets rendered.
    """
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    cards = []
    for row in rows:
        examples = []
        for at in range(1, EXAMPLES + 1):
            german = (row.get(f"german{at}") or "").strip()
            if not german:
                continue
            examples.append(Example(
                text=german,
                translation=(row.get(f"english{at}") or "") or None,
                means=(row.get(f"means{at}") or "") or None))
        cards.append(Card(
            position=int(row["position"]),
            word=row["word"],
            is_pattern=row.get("pattern") == "pattern",
            examples=tuple(examples),
            beside=(row.get("beside") or "") or None,
            total=len(rows),
            spoken=row.get("spoken") or "",
        ))
    return cards
