"""Queries against `word_table` — the shared word catalogue."""
from __future__ import annotations

from dataclasses import dataclass

# STTS tags grouped into the closed word classes.  These are the categories a
# learner acquires wholesale rather than one item at a time, which is why they
# get their own review file instead of being mixed into `known_words.txt`.
CLOSED_CLASS: dict[str, tuple[str, ...]] = {
    "Artikel":                  ("ART",),
    "Personalpronomen":         ("PPER",),
    "Reflexivpronomen":         ("PRF",),
    "Possessivpronomen":        ("PPOSAT", "PPOSS"),
    "Demonstrativpronomen":     ("PDS", "PDAT"),
    "Indefinitpronomen":        ("PIS", "PIAT", "PIDAT"),
    "Relativpronomen":          ("PRELS", "PRELAT"),
    "Fragewörter":              ("PWS", "PWAT", "PWAV"),
    "Pronominaladverbien":      ("PROAV", "PAV"),
    "Präpositionen":            ("APPR", "APPRART", "APPO", "APZR"),
    "Konjunktionen":            ("KON", "KOUS", "KOUI", "KOKOM"),
    "Partikeln":                ("PTKNEG", "PTKZU", "PTKA", "PTKVZ", "PTKANT"),
    "Hilfsverben":              ("VAFIN", "VAINF", "VAPP", "VAIMP"),
    "Modalverben":              ("VMFIN", "VMINF", "VMPP"),
}

# Tags whose tokens are never vocabulary to be learned.
PUNCTUATION_TAGS = frozenset({"$.", "$,", "$("})
FREE_TAGS = frozenset({"NE", "CARD", "FM", "XY"})


@dataclass(frozen=True)
class FunctionWord:
    """One closed-class lemma, with the evidence a reader needs to judge it."""

    lemma: str
    category: str
    frequency: int
    examples: tuple[str, ...]


class WordRepository:
    def __init__(self, db, language: str = "de") -> None:
        self._db = db
        self._language = language

    def lemmas_for_surfaces(self, surfaces: list[str]) -> set[str]:
        """Corpus lemmas matching any of `surfaces`, by surface *or* by lemma."""
        rows = self._db.rows(
            """
            SELECT DISTINCT lower(lemma)
              FROM word_table
             WHERE language = %s
               AND (word_norm = ANY(%s) OR lower(lemma) = ANY(%s))
            """,
            (self._language, surfaces, surfaces),
        )
        return {row[0] for row in rows}

    def function_words(self) -> list[FunctionWord]:
        """Every closed-class lemma present in the corpus, most frequent first.

        Junk from the tagger (numerals, clitics like `'n`, fragments carrying
        punctuation) is dropped here rather than pushed onto the reader.
        """
        tag_to_category = {
            tag: category
            for category, tags in CLOSED_CLASS.items()
            for tag in tags
        }
        rows = self._db.rows(
            """
            SELECT lower(lemma)              AS lemma,
                   min(tag)                  AS tag,
                   sum(frequency)::int       AS frequency,
                   array_agg(DISTINCT word)  AS examples
              FROM word_table
             WHERE language = %s
               AND tag = ANY(%s)
             GROUP BY lower(lemma)
             ORDER BY sum(frequency) DESC
            """,
            (self._language, list(tag_to_category)),
        )
        out: list[FunctionWord] = []
        for lemma, tag, frequency, examples in rows:
            if not self._is_real_word(lemma):
                continue
            out.append(FunctionWord(
                lemma=lemma,
                category=tag_to_category[tag],
                frequency=frequency,
                examples=tuple(sorted(examples)[:4]),
            ))
        return out

    @staticmethod
    def _is_real_word(lemma: str) -> bool:
        return bool(lemma) and lemma.isalpha() and len(lemma) > 1
