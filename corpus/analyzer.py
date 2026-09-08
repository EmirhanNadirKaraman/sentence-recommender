"""Deriving a sentence's learning units by running the matcher over it.

Units come from the *corrected* text, not from the `word_to_sentence` bridge.
That bridge is keyed to the raw subtitle rows, so once a sentence has been
reassembled or repunctuated it no longer describes what the learner reads.
Running the matcher live keeps units and displayed sentence in step — and it
is the same matcher that produced the bridge in the first place.

Two kinds come out:
  lemma   — content words, from spaCy's lemmatiser
  pattern — a `phrase_table.canonical`, e.g. "jdm. (Dat) etw. (Akk) geben",
            kept only when the matcher's blueprint is a registered pattern
            rather than a plain dictionary look-up

Two corrections are applied on the way, both for the same underlying reason:
the small German model is unreliable on a capitalised word at the start of a
sentence, where German gives it no case signal to work with.  See
`_lemma_for` and `_proper_nouns`.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from corpus.sentence import Sentence
from db.word_repo import FREE_TAGS, PUNCTUATION_TAGS
from vocab.entry import Unit

_MATCHER_DIR = Path(__file__).resolve().parents[1] / "matcher"

VERB_TAGS = ("VV", "VA", "VM")


class UnitAnalyzer:
    """Wraps the vendored matcher.  spaCy loads on first use, not on import."""

    def __init__(
        self,
        pattern_vocabulary: frozenset[str],
        language: str = "de",
        processes: int = 1,
    ) -> None:
        self._patterns = pattern_vocabulary
        self._language = language
        self._processes = processes
        self._matcher = None

    @property
    def matcher(self):
        if self._matcher is None:
            if str(_MATCHER_DIR) not in sys.path:
                sys.path.insert(0, str(_MATCHER_DIR))
            import phrase_finder            # noqa: PLC0415 — deferred, loads spaCy
            self._matcher = phrase_finder
        return self._matcher

    def analyze_all(self, sentences: list[Sentence]) -> list[Sentence]:
        """Attach units to every sentence.

        `processes` > 1 forks spaCy workers for the parse, which is the
        expensive half; pattern extraction stays in this process because it
        walks the parsed Doc.  Worth it only for the full corpus — for a
        handful of sentences the fork cost dominates.
        """
        docs = self.matcher.nlp.pipe(
            [s.text for s in sentences],
            batch_size=500,
            n_process=self._processes if len(sentences) > 5_000 else 1,
        )
        names: Counter[str] = Counter()
        content: Counter[str] = Counter()
        by_surface: dict[str, Counter[str]] = defaultdict(Counter)
        analysed = [
            s.with_units(*self._units(doc, names, content, by_surface))
            for s, doc in zip(sentences, docs)
        ]
        return self._normalise(
            analysed,
            self._proper_nouns(names, content),
            self._lemma_corrections(by_surface),
        )

    def lemmas(self, texts: list[str]) -> set[str]:
        """Lemmatise arbitrary text with the same model the corpus was parsed by.

        Used to resolve the vocabulary files into the corpus's own lemma space,
        so a known word and its corpus occurrences cannot disagree.
        """
        out: set[str] = set()
        for doc in self.matcher.nlp.pipe(texts, batch_size=256):
            out.update(
                token.lemma_.strip().lower()
                for token in doc if self._is_content(token)
            )
        return out

    # --- unit extraction -------------------------------------------------

    def _units(self, doc, names: Counter, content: Counter, by_surface: dict):
        units: set[Unit] = set()
        surfaces: dict[Unit, str] = {}
        for token in doc:
            if token.tag_ in PUNCTUATION_TAGS or token.is_punct or token.is_space:
                continue
            lemma = self._lemma_for(token)
            if not lemma:
                continue
            if token.tag_ in FREE_TAGS:
                names[lemma] += 1
                continue
            content[lemma] += 1
            by_surface[token.text.lower()][lemma] += 1
            unit = Unit.lemma(lemma)
            units.add(unit)
            surfaces.setdefault(unit, token.text)
        for phrase in self.matcher.extract_phrases(doc, self._language):
            entry = phrase["dictionary_entry"]
            if entry in self._patterns:
                unit = Unit.pattern(entry)
                units.add(unit)
                surfaces.setdefault(unit, " ".join(phrase["sentence_phrase"]))
        return frozenset(units), tuple(surfaces.items())

    def _lemma_for(self, token) -> str:
        """`token`'s lemma, retried in lower case when the model gave up.

        A sentence-initial finite verb often comes back unlemmatised, because
        German capitalises the first word of every sentence and the model has
        no case signal to work with there.  Asking again without the capital
        recovers many of them ("Hast" -> "haben"); the ones it does not are
        left to `_lemma_corrections`, which has the whole corpus to go on.

        Nouns are never retried: German capitalises them by rule, not by
        position, so their capital is real information.
        """
        lemma = token.lemma_.strip()
        if not lemma or lemma == "--":
            return ""
        if (lemma == token.text and lemma[:1].isupper()
                and token.tag_.startswith(VERB_TAGS)):
            return self._lemmatise_lower(lemma.lower()).lower()
        return lemma.lower()

    @lru_cache(maxsize=8192)
    def _lemmatise_lower(self, word: str) -> str:
        """Lemma of `word` parsed alone in lower case.  Cached — the set of
        words that trip the model is small and repeats constantly."""
        return self.matcher.nlp(word)[0].lemma_.strip() or word

    # --- corpus-wide corrections -----------------------------------------

    @staticmethod
    def _lemma_corrections(by_surface: dict) -> dict[str, str]:
        """Lemmas the model failed on, repaired from its own better guesses.

        A sentence-initial finite verb comes back unlemmatised — "Willst du
        das?" yields the lemma "willst", while "Du willst das" yields "wollen".
        German capitalises the first word of every sentence, so the model has
        no case signal there; mid-sentence it does.

        Re-parsing the word alone does not help — it has no context either.
        The corpus does: the same surface appears in both positions thousands
        of times, so the majority lemma for a surface repairs the minority
        failures.  Only identity lemmas (lemma == surface) are corrected; a
        genuine disagreement between two real lemmas is left alone.
        """
        corrections: dict[str, str] = {}
        for surface, lemmas in by_surface.items():
            if surface not in lemmas:
                continue                      # never failed on this surface
            best, _ = lemmas.most_common(1)[0]
            if best != surface:
                corrections[surface] = best
        return corrections

    # --- proper nouns ----------------------------------------------------

    @staticmethod
    def _proper_nouns(names: Counter, content: Counter) -> frozenset[str]:
        """Lemmas the model calls a name more often than not.

        Per-token tagging is unreliable at the start of a sentence: in "Gibst
        du das Tom?" the model tags the verb as a name and the name as a noun.
        Across a corpus the mistake is a minority, so the majority verdict is
        far more trustworthy than any single occurrence — and a name is not
        vocabulary the learner has to acquire.
        """
        return frozenset(
            lemma for lemma, count in names.items() if count > content.get(lemma, 0)
        )

    @staticmethod
    def _normalise(
        sentences: list[Sentence],
        proper: frozenset[str],
        corrections: dict[str, str],
    ) -> list[Sentence]:
        """Apply both corpus-wide passes: drop names, repair failed lemmas."""
        dropped = {Unit.lemma(lemma) for lemma in proper}
        remap = {
            Unit.lemma(wrong): Unit.lemma(right)
            for wrong, right in corrections.items()
        }
        if not dropped and not remap:
            return sentences

        out: list[Sentence] = []
        for sentence in sentences:
            if not (sentence.units & dropped or sentence.units & remap.keys()):
                out.append(sentence)
                continue
            units = {
                remap.get(u, u) for u in sentence.units if u not in dropped
            }
            surfaces = tuple(
                (remap.get(u, u), text)
                for u, text in sentence.surfaces if u not in dropped
            )
            out.append(sentence.with_units(frozenset(units), surfaces))
        return out

    @staticmethod
    def _is_content(token) -> bool:
        """Punctuation is not vocabulary; names and numbers are free.

        A proper noun or numeral does not make a sentence harder to read — you
        need not have learned "Dresden" to understand a sentence containing it
        — so neither counts toward the unknown tally.
        """
        if token.is_punct or token.is_space:
            return False
        if token.tag_ in PUNCTUATION_TAGS or token.tag_ in FREE_TAGS:
            return False
        return bool(token.lemma_.strip()) and token.lemma_ != "--"
