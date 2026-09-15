"""`detect-language` — say what language each stored sentence is in.

The transcripts are bilingual, and 5,228 of the corpus's 315,216 sentences
are English. Two of them are teaching steps of the beginner roadmap. Nothing
in the pipeline looked, and nothing cheap can: a word-list test finds four of
them and misses the two that matter, because their English contains `so` and
`also`, which are German words as well.

`lingua` rather than `langdetect`, and that was measured rather than assumed.
Over 600 real sentences from the plan, langdetect flagged seven as
not-German, of which five were plainly German — `Papa, wann können wir Samuel
abholen?` among them. lingua flagged two and both were English. langdetect is
a port of a library built for documents and it is unreliable on one short
line, which is all this corpus has; lingua is built for exactly that, and was
seven times faster here besides.

A backfill rather than a step in the import, so this costs no rebuild. The
column is nullable and NULL means nobody has looked, so a corpus that has
never run this behaves exactly as it did.
"""
from __future__ import annotations

import re
import time

# `de` and `en` because those are the two languages in the material: German
# videos with English subtitling alongside. Given the whole of lingua's
# catalogue it would find Dutch in some German, which is true and unhelpful.
CHOICES = ("de", "en")
BATCH = 5000

# What a sentence quotes is not what language the sentence is in. A bilingual
# transcript renders `Mathias, wann sagt man "Du gehst mir auf den Keks"?`
# into English and keeps the idiom in German, so six of the eleven words in
# the English line are German and every detector calls the whole thing
# German. Judging the frame instead gets it right, and leaves the German
# sentence quoting German exactly where it was.
QUOTED = re.compile(r'"[^"]*"|„[^“]*“|«[^»]*»|\'[^\']{6,}\'')
# Below this, the remainder is too short to judge and the whole sentence is
# used instead — `"Schaun mer mol, dann seng ma scho".` is nothing but quote.
ENOUGH_WORDS = 3


def language_of(text: str, detector) -> str:
    """`de` or `en`, judged on the sentence outside anything it quotes.

    Undetectable is German, not English: this is German material, and a line
    too short to judge — `Ja.`, `Genau.` — is far likelier to be the language
    everything else is in than the one that leaks into it.
    """
    from lingua import Language                           # noqa: PLC0415

    outside = QUOTED.sub(" ", text).strip()
    judged = outside if len(outside.split()) >= ENOUGH_WORDS else text
    return "en" if detector.detect_language_of(judged) == Language.ENGLISH \
        else "de"


class DetectLanguageCommand:
    def run(self, app, rebuild: bool = False, limit: int | None = None) -> None:
        from lingua import Language, LanguageDetectorBuilder  # noqa: PLC0415  # noqa: F401
        from psycopg2.extras import execute_batch             # noqa: PLC0415

        detector = (LanguageDetectorBuilder
                    .from_languages(Language.GERMAN, Language.ENGLISH)
                    .build())
        store = app.corpus_store
        # Paged by id rather than by the filter. Without `language IS NULL`
        # to exclude what has been done — which is what `--rebuild` asks for
        # — a plain LIMIT reads the same first rows for ever.
        unjudged = "" if rebuild else " AND language IS NULL"
        with store._conn().cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM corpus_sentence"
                        " WHERE true" + unjudged)
            total = cur.fetchone()[0]
        if not total:
            print("every sentence already has a language — "
                  "`--rebuild` to do them again")
            return
        print(f"{total:,} sentences to read", flush=True)

        started = time.perf_counter()
        seen, after = 0, 0
        counts = {"de": 0, "en": 0}
        while True:
            with store._conn().cursor() as cur:
                cur.execute(
                    "SELECT id, text FROM corpus_sentence WHERE id > %s"
                    + unjudged + " ORDER BY id LIMIT %s", (after, BATCH))
                rows = cur.fetchall()
            if not rows:
                break
            found = []
            for sentence_id, text in rows:
                name = language_of(text, detector)
                counts[name] += 1
                found.append((name, sentence_id))
            with store._conn().cursor() as cur:
                execute_batch(
                    cur, "UPDATE corpus_sentence SET language = %s WHERE id = %s",
                    found, page_size=1000)
            seen += len(rows)
            after = rows[-1][0]
            rate = seen / max(time.perf_counter() - started, 1e-9)
            print(f"  … {seen:,}/{total:,} · {counts['en']:,} English · "
                  f"{rate:,.0f}/s", flush=True)
            if limit and seen >= limit:
                break

        spent = time.perf_counter() - started
        print(f"\n{seen:,} read in {spent:.0f}s")
        print(f"  German  {counts['de']:>7,}")
        print(f"  English {counts['en']:>7,}  "
              f"({counts['en'] / max(seen, 1):.2%})")
        print("  the algorithms skip these; the overlay still shows them, "
              "because they were still said")
