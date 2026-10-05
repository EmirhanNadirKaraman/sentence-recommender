"""What changes when the language being learned changes.

This project was written for German, and German is in it at every level:
the parser, the repairs made to what the parser says, the notation the study
list writes a verb in, the words a filter recognises as foreign. A second
language does not change what the program does -- find the sentences that
are one word away, teach them, review them -- only the tables it does that
with, and those are gathered here.

German's entries are exactly what the code used before this file existed,
and must stay so. The German corpus is fingerprinted on the files its rules
live in (see `fingerprint`), and a German value changed here would quietly
change every German plan.

Each language keeps its catalogue and corpus in a schema of its own, inside
the one database. Both are keyed by build name -- `subtitle`, `generated` --
and a second language writing a `subtitle` build into the same tables would
delete the first's on its next rebuild. A schema holds tables of the same
names, so every query in the program reads one language's without knowing
it, and German's stays in `public`, where it always was.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


@dataclass(frozen=True)
class Language:
    """One language a reader can learn."""

    # ISO 639-1, as `video.language` and `corpus_sentence.language` store it.
    code: str
    # In English, because that is what the prompts and the pages are written
    # in -- "Translate this German sentence", not "Deutsch".
    name: str
    # The Postgres schema its catalogue and corpus live in. Empty for German,
    # which predates there being a second language and keeps `public`.
    schema: str
    # The closed classes, counted as known before anything is taught.
    function_words: Path
    # Fixed expressions, found by their words. See `vocab.expressions`.
    expressions: Path
    # Hand corrections for study-list entries the parser misreads alone.
    goal_lemmas: Path
    # The two halves `build-study-list` merges. German only: no other
    # language has a valency dictionary to merge with.
    order_words: Path | None = None
    form_words: Path | None = None
    # Builds that exist but are not studied from.
    ignored_builds: frozenset[str] = frozenset()
    # Words a word list writes before an entry that are not the entry:
    # German's articles (`der Abend`), English's `the` and the `to` of an
    # infinitive (`to abandon`).
    markers: frozenset[str] = frozenset()
    # Words a dictionary writes where a phrase goes: `take sth into
    # account`. German writes its own (`jdm. (Dat)`), and its code reads
    # them; see `vocab.aliases`.
    slots: frozenset[str] = frozenset()
    # Whether `data/compounds.txt` applies: words built of words the list
    # already teaches, granted when their parts are known.
    compounds: bool = False
    # The commonest content words, counted as known from the start like the
    # function words: what a new reader's `known_words.txt` begins as.
    starter_words: Path | None = None
    # Added to a word when searching YouTube for video that says it: `Haus
    # deutsch` finds German, and English needs nothing added to find English.
    search_suffix: str = ""
    # Whether a hand-written track counts only over speech in the same
    # language. YouTube files a machine track under the language it heard,
    # so a German video carrying hand-written English subtitles says so --
    # and those subtitles are a translation, not English anyone said. German
    # was catalogued before this test existed and keeps what it has; see
    # `ingest.video`.
    spoken_only: bool = False


GERMAN = Language(
    code="de",
    name="German",
    schema="",
    function_words=DATA / "function_words.txt",
    expressions=DATA / "expressions.txt",
    goal_lemmas=DATA / "goal_lemmas.txt",
    order_words=DATA / "old_data" / "words_4000.txt",
    form_words=DATA / "final_result.txt",
    # Tatoeba's sentences were imported once and are kept -- deleting them
    # is irreversible now the importer is gone -- but nothing reads them:
    # the German corpus is video subtitles.
    ignored_builds=frozenset({"tatoeba"}),
    # `vocab.loader.ARTICLES`, which is what reads them; a test holds the
    # two together.
    markers=frozenset({"der", "die", "das", "den", "dem", "des"}),
    compounds=True,
    search_suffix=" deutsch",
)

ENGLISH = Language(
    code="en",
    name="English",
    schema="en",
    function_words=DATA / "en" / "function_words.txt",
    expressions=DATA / "en" / "expressions.txt",
    goal_lemmas=DATA / "en" / "goal_lemmas.txt",
    starter_words=DATA / "en" / "starter_words.txt",
    markers=frozenset({"the", "a", "an", "to"}),
    slots=frozenset("""
    sb sth sb's sth's smb smth somebody someone something one's oneself
    """.split()),
    spoken_only=True,
)

LANGUAGES: dict[str, Language] = {lang.code: lang for lang in (GERMAN, ENGLISH)}

# What a translation can be made into. Wider than `LANGUAGES`: a reader
# learns one of those, and is helped in whatever they already speak.
NATIVE: dict[str, str] = {"en": "English", "tr": "Turkish", "de": "German"}


def language(code: str) -> Language:
    """The language named by `code`, or a clear refusal."""
    try:
        return LANGUAGES[code]
    except KeyError:
        known = ", ".join(sorted(LANGUAGES))
        raise SystemExit(f"no language {code!r} -- this project knows {known}") from None
