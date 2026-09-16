"""`judge-sentences` — the faults a sentence's own characters cannot show.

`corpus.quality.score` reads a sentence and sees its length, its variety, how
it opens and whether it trails off. Three things it cannot see, because none
of them are in the text itself:

  *no finite verb.* `Zum Beispiel von Markus Söder, dem Chef der CSU.` is well
  punctuated, a good length, every word ordinary German -- and it is a caption,
  a fragment of whatever sentence the speaker was in the middle of.

  *an English word.* `detect-language` judged whole sentences and took out
  12,649 English ones. What it could not take out is a German sentence
  carrying its own translation: `Trinken, feiern, Spaß haben, Drinking,
  partying, having fun.` is German by any measure and half of it is not.

  *a name nobody has met.* `Wetu, wir sind jetzt hier bei Penduka` teaches
  `Penduka` to nobody. The test is not whether a name is German -- `Sachsen-
  Anhalt` and `Saudi-Arabien` are fine -- but whether this corpus says it
  often enough for a reader to have met it.

All three are recorded as verdicts, which the example ranking already reads
above quality. Nothing is deleted: a word whose only example is a fragment is
still taught with it, ranked last.

Which words are English is measured rather than looked up in a list. Every
corpus sentence is marked `de` or `en`, so a word is judged by the company it
keeps -- `ask` and `anything` live in the English sentences, `diese` and
`wäre` overwhelmingly in the German ones. An earlier version asked the corpus
lexicon instead and called `zum`, `wäre` and `hatte` foreign, because that
table holds content words only.
"""
from __future__ import annotations

import re
import time
from collections import Counter

from corpus.overrides import SentenceOverrides

# STTS, the same tags the analyser reads. A main clause needs a finite verb;
# an infinitive alone is a subordinate fragment with nothing to be under.
FINITE = frozenset(("VVFIN", "VAFIN", "VMFIN", "VVIMP", "VAIMP"))
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# A word is English-leaning when English sentences say it at least this often
# and German ones say it no more than a quarter as much. Both parts matter:
# the floor keeps one-off typos out, the ratio keeps `Information` in.
ENGLISH_FLOOR = 3
ENGLISH_RATIO = 0.25

# How often the German corpus must say a name for a reader to have met it.
KNOWN_NAME = 5
# People only. Places and organisations were tried and withdrawn: German
# builds nouns by gluing them together, the tagger reads a rare compound as an
# organisation, and a rare compound is rare by definition -- so `Dreieckshandel`,
# `Angebotszettel` and `Senkblei` were each charged for being an unfamiliar
# name. Restricting to people took the flagged share from 1.50% to 0.70% and
# left almost only real names behind.
NAME_LABELS = frozenset(("PER",))

# Multiplied together, so a verbless sentence carrying an English word is
# charged for both. Anything under 1.0 sorts behind every sentence nobody has
# complained about, because the ranking reads the verdict before the quality.
NO_VERB = 0.4
ENGLISH = 0.3
STRANGE_NAME = 0.8

SOURCE = "parser"
BATCH = 256
REPORT = 25_000


def english_tokens(rows) -> tuple[set[str], Counter]:
    """Words that live in the English sentences and not the German ones.

    Returns those words and the German counts beside them, because the name
    test needs the same tally and counting 450,547 sentences twice would be
    the slowest thing in this command.
    """
    german, english = Counter(), Counter()
    for text, language in rows:
        seen = {word.lower() for word in WORD.findall(text or "")}
        (english if language == "en" else german).update(seen)
    return {word for word, count in english.items()
            if count >= ENGLISH_FLOOR
            and german.get(word, 0) <= count * ENGLISH_RATIO}, german


def strange_name(doc, german: Counter) -> bool:
    """A named thing this corpus barely says.

    Every part of the name is looked up and the most familiar one decides, so
    `Cambridge Analytica` is strange only if neither word is known. The name
    is stripped of punctuation first -- `Sarah!` looked up whole finds
    nothing -- and one with no capital letter in it is the tagger being
    wrong, because German capitalises what it names.
    """
    for entity in doc.ents:
        if entity.label_ not in NAME_LABELS:
            continue
        parts = WORD.findall(entity.text)
        if not parts or not any(part[:1].isupper() for part in parts):
            continue
        if max(german.get(part.lower(), 0) for part in parts) < KNOWN_NAME:
            return True
    return False


class JudgeSentencesCommand:
    def run(self, app, limit: int | None = None, dry_run: bool = False) -> None:
        import spacy                                        # noqa: PLC0415

        from db import Database                             # noqa: PLC0415

        settings = app.settings
        with Database(settings.own) as db:
            english, german = english_tokens(
                db.rows("SELECT text, language FROM corpus_sentence"))
        print(f"{len(english):,} English-leaning tokens · "
              f"{len(german):,} seen in German sentences", flush=True)

        sentences = app.corpus()
        if limit:
            sentences = sentences[:limit]
        if not sentences:
            raise SystemExit("no cached corpus — run `build-corpus` first")

        # NER is wanted here, unlike the verb-only pass, so it stays in.
        nlp = spacy.load("de_core_news_md", exclude=["lemmatizer"])
        texts = [s.text for s in sentences]
        print(f"{len(texts):,} sentences · de_core_news_md", flush=True)

        start = time.perf_counter()
        verdicts: dict[str, float] = {}
        counts = Counter()
        suspect: list[str] = []
        for done, doc in enumerate(nlp.pipe(texts, batch_size=BATCH), start=1):
            text = doc.text
            penalty = 1.0
            if not {token.tag_ for token in doc} & FINITE:
                suspect.append(text)            # second look before charging
            if any(word.lower() in english for word in WORD.findall(text)):
                penalty *= ENGLISH
                counts["an English word"] += 1
            if strange_name(doc, german):
                penalty *= STRANGE_NAME
                counts["a name nobody has met"] += 1
            if penalty < 1.0:
                verdicts[text] = penalty
            if done % REPORT == 0:
                print(f"  … {done:,} read · {len(verdicts):,} marked",
                      flush=True)

        # German capitalises its nouns, so a sentence *opening* on a finite
        # verb reads as a noun to the tagger: `Schreib mir bitte eine kurze
        # E-Mail` and `Wünschen Sie sich eher einen Jungen?` were both called
        # verbless. Lowercasing the first word removes the only cue that
        # misled it, and rescued 1,281 of 18,975 in the measured run.
        lowered = [text[:1].lower() + text[1:] for text in suspect]
        for text, doc in zip(suspect, nlp.pipe(lowered, batch_size=BATCH)):
            if {token.tag_ for token in doc} & FINITE:
                continue
            verdicts[text] = verdicts.get(text, 1.0) * NO_VERB
            counts["no finite verb"] += 1
        spent = time.perf_counter() - start

        print(f"\n{len(verdicts):,} sentences marked · "
              f"{len(verdicts) / len(texts):.1%} of the corpus · {spent / 60:.1f} min")
        for why, n in counts.most_common():
            print(f"  {n:>7,}  {why}")
        print(f"  {len(suspect) - counts['no finite verb']:>7,}  "
              "were the tagger misreading a sentence that opens on its verb")

        if dry_run:
            print("\ndry run — nothing written")
            for text in list(verdicts)[:12]:
                print(f"  {verdicts[text]:.2f}  {text[:66]}")
            return

        app.overrides.mark_many(verdicts, SOURCE)
        print(f"\nwrote {len(verdicts):,} verdicts as '{SOURCE}'")
        print("  rebuild the roadmap to re-pick examples with these demoted")
