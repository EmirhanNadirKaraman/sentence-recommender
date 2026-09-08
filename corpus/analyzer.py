"""Deriving a sentence's learning units by running the matcher over it.

Units come from the *corrected* text, not from the `word_to_sentence` bridge.
That bridge is keyed to the raw subtitle rows, so once a sentence has been
reassembled or repunctuated it no longer describes what the learner reads.
Running the matcher live keeps units and displayed sentence in step — and it
is the same matcher that produced the bridge in the first place.

Two kinds of unit come out:
  lemma   — content words, from spaCy's lemmatiser
  pattern — a `phrase_table.canonical`, e.g. "jdm. (Dat) etw. (Akk) geben",
            kept only when the matcher's blueprint is a registered pattern
            rather than a plain dictionary look-up

Analysis is two passes over the corpus, because the model's per-token output
is not trustworthy enough to use directly.  The first pass reads every token,
repairs the lemma where the model plainly gave up, and tallies evidence; the
second acts on that evidence.  See `_verb_lemma`, `_lemma_corrections` and
`_proper_nouns` for what each repair fixes and why.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from corpus.sentence import Sentence
from db.word_repo import FREE_TAGS, PUNCTUATION_TAGS
from vocab.entry import Unit

_MATCHER_DIR = Path(__file__).resolve().parents[1] / "matcher"
_OVERRIDES = Path(__file__).resolve().parents[1] / "data" / "lemma_overrides.txt"

VERB_TAGS = ("VV", "VA", "VM")

# The matcher falls back to trigram similarity when nothing matches outright,
# and reports the score in `match_type`. Measured over the subtitle corpus,
# everything below a perfect score is guesswork: 0.62 turned "Epsteins" into
# "der Stein" and "alles" into "die Halle". A score of 1.00 means the trigram
# sets matched exactly — an inflection, not a guess — and covers 65% of fuzzy
# matches. The rest are dropped.
FUZZY_SCORE = re.compile(r"fuzzy \(([0-9.]+)\)")
MIN_FUZZY = 1.0

# A German infinitive ends in -en or -n.  A verb lemma that already looks like
# one is almost certainly right, and must not be "corrected" — this is the
# guard that keeps `sein` and `haben` away from the lookup table below.
INFINITIVE_ENDINGS = ("en", "n")

# How decisively a competing lemma must outnumber an apparent failure before
# the corpus vote overrides it.  See `_lemma_corrections`.
CORRECTION_MARGIN = 4


class Evidence:
    """What the first pass tallies, so the second can correct the first."""

    def __init__(self) -> None:
        self.names: Counter[str] = Counter()
        self.content: Counter[str] = Counter()
        self.by_surface: dict[str, Counter[str]] = defaultdict(Counter)


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
        self._verb_lemmas: "_LemmaLookup | None" = None

    @property
    def verb_lemmas(self) -> "_LemmaLookup":
        """Surface -> infinitive, for verb forms the parser cannot reduce.

        Two sources: `data/lemma_overrides.txt` for hand-checked corrections,
        and spaCy's German lookup table (355k entries) underneath.

        That table is context-free and must never be applied broadly — it maps
        `sein` to `mein`, `sie` to `ich` and `ein` to `einen`, because it
        conflates whole pronoun paradigms.  `_verb_lemma` is what makes it
        safe, by consulting it only where the alternative is a lemma already
        known to be wrong.
        """
        if self._verb_lemmas is None:
            self._verb_lemmas = _LemmaLookup(
                self._lookup_table(), self._read_overrides()
            )
        return self._verb_lemmas

    def _lookup_table(self):
        """spaCy's German lemma table, or None if the package is not installed.

        `spacy-lookups-data` is an optional data package, so its absence has
        to degrade lemma repair rather than stop the program — the
        corpus-majority pass still runs and `data/lemma_overrides.txt` still
        applies. It is worth saying out loud though: without the table,
        inflected forms like "willst" and "musst" stay separate units from
        their infinitives, and a corpus built that way is measurably worse.
        """
        try:
            from spacy.lookups import load_lookups   # noqa: PLC0415 — heavy
            return load_lookups(self._language, ["lemma_lookup"]).get_table(
                "lemma_lookup"
            )
        except Exception as error:              # noqa: BLE001 — optional data
            print(
                f"\nWARNING: no spaCy lemma table for {self._language!r} "
                f"({type(error).__name__}).\n"
                "  spacy-lookups-data is missing from THIS interpreter. It also "
                "changes how\n  spaCy itself lemmatises: without it \"musst\" "
                "resolves to \"mussen\" rather than\n  \"müssen\", so inflected "
                "forms stay separate from their infinitives and\n  any corpus "
                "built now will be measurably worse.\n"
                "  fix: pip install spacy-lookups-data   (or use .venv/bin/python)\n",
                file=sys.stderr, flush=True,
            )
            return None

    @staticmethod
    def _read_overrides() -> dict[str, str]:
        if not _OVERRIDES.exists():
            return {}
        out: dict[str, str] = {}
        for raw in _OVERRIDES.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].split()
            if len(line) == 2:
                out[line[0].lower()] = line[1].lower()
        return out

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
        self.verb_lemmas          # load the table now, so its absence is said once
        docs = self.matcher.nlp.pipe(
            [s.text for s in sentences],
            batch_size=500,
            n_process=self._processes if len(sentences) > 5_000 else 1,
        )
        evidence = Evidence()
        analysed = [
            s.with_units(*self._units(doc, evidence))
            for s, doc in zip(sentences, docs)
        ]
        return self._normalise(
            analysed,
            self._proper_nouns(evidence),
            self._lemma_corrections(evidence),
        )

    def lemmas(self, texts: list[str]) -> set[str]:
        """Lemmatise arbitrary text with the same model the corpus was parsed by.

        Used to resolve the vocabulary files into the corpus's own lemma space,
        so a known word and its corpus occurrences cannot disagree.
        """
        self.verb_lemmas          # as above: report a missing table up front
        out: set[str] = set()
        for doc in self.matcher.nlp.pipe(texts, batch_size=256):
            out.update(
                self._verb_lemma(token) for token in doc if self._is_content(token)
            )
        return out

    # --- first pass ------------------------------------------------------

    def _units(self, doc, evidence: Evidence):
        units: set[Unit] = set()
        surfaces: dict[Unit, str] = {}
        for token in doc:
            if token.tag_ in PUNCTUATION_TAGS or token.is_punct or token.is_space:
                continue
            lemma = self._verb_lemma(token)
            if not lemma:
                continue
            if token.tag_ in FREE_TAGS:
                evidence.names[lemma] += 1
                continue
            evidence.content[lemma] += 1
            evidence.by_surface[token.text.lower()][lemma] += 1
            unit = Unit.lemma(lemma)
            units.add(unit)
            surfaces.setdefault(unit, token.text)
        for phrase in self.matcher.extract_phrases(doc, self._language):
            entry = phrase["dictionary_entry"]
            if entry not in self._patterns or not self._trustworthy(phrase, doc):
                continue
            unit = Unit.pattern(entry)
            units.add(unit)
            surfaces.setdefault(unit, " ".join(phrase["sentence_phrase"]))
        return frozenset(units), tuple(surfaces.items())

    @staticmethod
    def _trustworthy(phrase, doc) -> bool:
        """Is this pattern match evidence, or a guess?

        Two ways it is not. A weak trigram score means the matcher found
        nothing and settled for something shaped alike — that is where
        "Epsteins" became "der Stein". And a match sitting entirely on proper
        nouns is matching a name: "Merkel" is not the verb "merken", and
        "Bayern" is not "der Bayer". Names are excluded from the word side
        already; this is the same rule for the pattern side.
        """
        score = FUZZY_SCORE.search(phrase["match_type"])
        if score and float(score.group(1)) < MIN_FUZZY:
            return False
        tags = {doc[i].tag_ for i in phrase["indices"] if i < len(doc)}
        return not (tags and tags <= {"NE"})

    def _verb_lemma(self, token) -> str:
        """`token`'s lemma, with an inflected verb folded into its infinitive.

        The model leaves many second-person forms unreduced — "willst",
        "musst", "gibst", "nimmst" — in every position, not just at the start
        of a sentence, so `wollen` and `willst` become separate units and a
        learner who knows the verb still meets it as unknown. The stem vowel
        changes, so no rule recovers it; a lookup does.

        Three guards keep the lookup from doing harm, and all three matter:

          the parser called it a verb    — so a pronoun or article is never touched
          its lemma equals its surface   — so only an evident failure is overridden
          the surface is not already an infinitive
                                         — so "sein" and "haben", whose lemma
                                           correctly is themselves, are left alone

        The second guard is why the table never overrides a lemma the parser
        actually produced.  Measured over the subtitle corpus, the two disagree
        on 6% of the verb forms the table knows, and where the parser gives a
        real lemma it is generally the right one: it has "gehört" as "gehören"
        and "fällt" as "fallen", where the table says "hören" and "fällen" —
        different verbs.  The table only wins where the parser produced
        nothing usable.
        """
        lemma = token.lemma_.strip().lower()
        if not lemma or lemma == "--":
            return ""
        surface = token.text.lower()
        if (lemma == surface
                and token.tag_.startswith(VERB_TAGS)
                and not surface.endswith(INFINITIVE_ENDINGS)):
            return self.verb_lemmas.get(surface, lemma)
        return lemma

    # --- second pass -----------------------------------------------------

    def _lemma_corrections(self, evidence: Evidence) -> dict[str, str]:
        """Lemmas the model failed on, repaired from better evidence.

        A sentence-initial finite verb comes back unlemmatised — "Willst du
        das?" yields "willst", while "Du willst das" yields "wollen".  German
        capitalises the first word of every sentence, so the model has no case
        signal there; mid-sentence it does.

        Two repairs, strongest evidence first:

        1. The corpus.  The same surface appears in both positions thousands of
           times, so the majority lemma for a surface fixes the minority
           failures.  Only identity lemmas are touched — a disagreement between
           two real lemmas is left alone.
        This catches what `_verb_lemma` cannot: a token the parser did not tag
        as a verb at all.  Sentence-initial "Willst" comes back tagged as a
        conjunction, so the verb guard never lets it near the lookup, but the
        same word mid-sentence resolves to "wollen" hundreds of times.

        Only identity lemmas are touched, and a correction needs one of two
        things:

          * the lookup table independently proposes the same lemma — two
            unrelated sources agreeing is enough on its own; or
          * the alternative outnumbers the failure by `CORRECTION_MARGIN`.

        The margin exists because some words really are two words.  "weiß" is
        both a colour and a form of "wissen" and both readings are frequent;
        the lookup has no entry for it, so nothing overrides the margin and the
        two stay apart.  Flattening them would be worse than the failure.
        """
        corrections: dict[str, str] = {}
        for surface, lemmas in evidence.by_surface.items():
            failures = lemmas.get(surface, 0)
            if not failures:
                continue                      # never failed on this surface
            best, count = lemmas.most_common(1)[0]
            if best == surface:
                continue
            corroborated = self.verb_lemmas.get(surface) == best
            if corroborated or count >= failures * CORRECTION_MARGIN:
                corrections[surface] = best
        return corrections

    @staticmethod
    def _proper_nouns(evidence: Evidence) -> frozenset[str]:
        """Lemmas the model calls a name more often than not.

        Per-token tagging is unreliable at the start of a sentence: in "Gibst
        du das Tom?" the model tags the verb as a name and the name as a noun.
        Across a corpus the mistake is a minority, so the majority verdict is
        far more trustworthy than any single occurrence — and a name is not
        vocabulary the learner has to acquire.
        """
        return frozenset(
            lemma for lemma, count in evidence.names.items()
            if count > evidence.content.get(lemma, 0)
        )

    @staticmethod
    def _normalise(
        sentences: list[Sentence],
        proper: frozenset[str],
        corrections: dict[str, str],
    ) -> list[Sentence]:
        """Apply both corpus-wide verdicts: drop names, repair failed lemmas."""
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
            units = {remap.get(u, u) for u in sentence.units if u not in dropped}
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


class _LemmaLookup:
    """Surface -> infinitive, from hand-written overrides over spaCy's table.

    Wraps rather than copies the table: spaCy's `Table` hashes its keys, so
    iterating it yields integers instead of words, and any dict built from it
    holds nothing but whatever was added afterwards.

    `table` may be None when the optional data package is absent, in which
    case only the overrides apply.
    """

    def __init__(self, table, overrides: dict[str, str]) -> None:
        self._table = table
        self._overrides = overrides

    def get(self, surface: str, default: str = "") -> str:
        if surface in self._overrides:
            return self._overrides[surface]
        if self._table is None:
            return default
        found = self._table.get(surface)
        return str(found).lower() if found else default
