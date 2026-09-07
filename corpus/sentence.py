"""The corpus unit: one sentence, with a trail back to where it came from."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from vocab.entry import Unit

# Where a sentence came from.  Origin decides how far it can be trusted and,
# for generated sentences, whether it was ever verified at all.
SUBTITLE = "subtitle"     # reassembled from the language-app subtitle corpus
TATOEBA = "tatoeba"       # a human-written Tatoeba pair, with its translation
GENERATED = "generated"   # synthesised by the local model to fill a gap


@dataclass(frozen=True)
class RawLine:
    """A single row of `sentence` — a subtitle line, not a sentence.

    Roughly a third do not end in punctuation and many are cut mid-clause,
    which is the whole reason a correction step exists.
    """

    sentence_id: int
    video_id: str
    start_time: float
    content: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class Sentence:
    """One sentence the learner might be shown.

    `text` is what they read and what the roadmap reasons about.  `raw_text`
    is the untouched source behind it, when correction changed anything — kept
    so both versions can be shown side by side and a bad correction is never
    invisible.
    """

    text: str
    origin: str = SUBTITLE
    translation: str | None = None
    raw_text: str | None = None
    source_ids: tuple[int, ...] = ()
    units: frozenset[Unit] = field(default_factory=frozenset)
    surfaces: tuple[tuple[Unit, str], ...] = ()

    @property
    def original(self) -> str:
        return self.raw_text if self.raw_text is not None else self.text

    @property
    def was_corrected(self) -> bool:
        return self.raw_text is not None and self.raw_text != self.text

    def with_units(
        self,
        units: frozenset[Unit],
        surfaces: tuple[tuple[Unit, str], ...] = (),
    ) -> "Sentence":
        return replace(self, units=units, surfaces=surfaces)

    def surface_of(self, unit: Unit) -> str | None:
        """How `unit` is written in this sentence — "hat" for the lemma "haben".

        Recorded during analysis so a review card can blank the word out
        without loading a parser.
        """
        for candidate, surface in self.surfaces:
            if candidate == unit:
                return surface
        return None

    def unknowns(self, known: frozenset[Unit]) -> frozenset[Unit]:
        return self.units - known
