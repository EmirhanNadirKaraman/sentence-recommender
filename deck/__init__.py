"""The roadmap as something you can carry away from the app.

A plan is a sequence of steps, each a word and the sentences that teach it.
On the page that is a rail you click through; off the page it wants to be a
document you can print, a slideshow you can drill, or a folder of audio you
can listen to on a walk. All three want the same thing out of a step, so they
are given it once here and rendered three ways.

`Card` is deliberately flat and free of the corpus: everything a renderer
needs is a string or an int by the time it arrives. A deck is built once and
handed to a writer, so a PDF and a PPTX of the same plan cannot disagree
about what step 412 says -- and the audio for step 412 is named from the same
`stem`, which is what lets a slideshow find the clip that belongs to it.

Four things are said about each step, in this order:

    die Geschichte                                        the word
    Was kann man aus der Geschichte anderer Länder lernen?  a sentence using it
    What can one learn from the history of other countries?  and its English
    die Geschichte means history.                          what the word means

The last two come from a local model -- see `deck.gloss` -- and are absent
until it has been run. Everything renders without them; the card is simply
shorter.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from deck.spoken import spoken

# German writes its umlauts out this way when it cannot print them, which is
# what a filename is. Done before the general strip below, because that would
# turn `ü` into `u` and make `fuhren` of `führen` -- a different word.
UMLAUTS = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
})
# Long enough for the longest key the list holds (40 characters, `sich mit
# jemandem über etwas unterhalten`) and short enough that the whole name
# stays comfortably inside every filesystem's limit.
SLUG_LIMIT = 48


def slug(text: str) -> str:
    """A word as something safe to put in a filename.

    Spaces become hyphens and umlauts are written out; anything else that is
    not a letter, digit or hyphen is dropped rather than transliterated by
    guesswork. The result keeps its capitals, because German nouns carry one
    and `00412-die-Geschichte` says more than `00412-die-geschichte`.
    """
    written = text.translate(UMLAUTS)
    # Everything left that is not plain ASCII -- one `é` across the whole
    # deck -- loses its accent rather than the letter under it.
    written = "".join(ch for ch in unicodedata.normalize("NFKD", written)
                      if not unicodedata.combining(ch))
    written = re.sub(r"[^A-Za-z0-9]+", "-", written).strip("-")
    return written[:SLUG_LIMIT].rstrip("-")


@dataclass(frozen=True)
class Example:
    """One sentence that teaches the step, and what the word means in it.

    `means` is glossed per sentence rather than per word, because a word that
    means one thing in the first example can mean another in the third — and
    a single gloss covering both has to hedge, which hands the disambiguating
    back to the one person who cannot yet do it.
    """

    text: str
    translation: str | None = None
    means: str | None = None


@dataclass(frozen=True)
class Card:
    """One step, as much of it as a document can show.

    `beside` is the second word on the steps where the walk had to relax --
    those are not i+1 and a reader is owed the difference rather than being
    handed a sentence with an unexplained second new word in it. Every
    renderer says so.
    """

    position: int
    word: str
    is_pattern: bool
    examples: tuple[Example, ...] = ()
    beside: str | None = None
    total: int = 0
    spoken: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not self.spoken:
            # The key is written for a matcher; `spoken` is the same word as
            # a voice can say it and a model can be asked about it.
            object.__setattr__(self, "spoken", spoken(self.word))

    @property
    def sentence(self) -> str:
        """The first example — the one the walk chose to teach from."""
        return self.examples[0].text if self.examples else ""

    @property
    def translation(self) -> str | None:
        return self.examples[0].translation if self.examples else None

    @property
    def glossed(self) -> bool:
        """Whether the model has answered for this card.

        All or nothing: a card's senses and translations are written in one
        transaction, so there is no half-glossed state. A card with no
        meaning anywhere has either not been reached yet or was refused —
        both mean "still owed", and both are worth showing, because the
        alternative is a sparse-looking card that a reader has to wonder
        about. Note a *translation* can be present without the model: some
        corpus sentences carry their own English already.
        """
        return any(example.means for example in self.examples)

    @property
    def stem(self) -> str:
        """The filename this card owns, without an extension.

        Position first and zero-padded, so a directory listing and the plan
        agree on order: two steps can teach words that sort the other way
        round, and a media player goes by the name. Then the word, because a
        folder of five-digit numbers tells you nothing about what you are
        scrubbing through — `00412-die-Geschichte` does.

        One property, so the clip, the slide that names it and the manifest
        row cannot drift apart.
        """
        return f"{self.position:05d}-{slug(self.spoken)}"


def cards_from(steps, decks=None, senses=None, english=None) -> list[Card]:
    """Turn stored roadmap steps into cards, in plan order.

    `decks` maps a position to the sentences that teach it, as
    `RoadmapStore.decks` returns them; without it a card gets the one
    sentence the step itself carries. `senses` and `english` are what the
    model has already said -- keyed by (kind, key, sentence) and by sentence
    -- so a card picks up work from an earlier run instead of repeating it.
    """
    total = len(steps)
    senses = senses or {}
    english = english or {}
    out = []
    for step in steps:
        said = (decks or {}).get(step.position)
        if said is None:
            said = [step.sentence] if step.sentence else []
        examples = tuple(
            Example(text=s.text,
                    translation=english.get(s.text) or s.translation,
                    means=senses.get((step.unit.kind, step.unit.key, s.text)))
            for s in said)
        out.append(Card(
            position=step.position,
            word=step.unit.key,
            is_pattern=step.unit.is_pattern,
            examples=examples,
            beside=step.beside.key if step.beside else None,
            total=total,
        ))
    return out
