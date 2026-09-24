"""Which lemmas are invented, found by asking a second parser.

Four ways of finding these by rule have already failed here, and all four
failed for one reason: everything available to check against is downstream of
the parser being checked.

  * "no surface ever equals the lemma" flagged 12,830, nearly all correct --
    a noun that only ever appears in the plural never shows its singular.
  * rebuilding the plural gives the wrong target: `atoma -> atomen`, where
    the lemma wanted is `atom`.
  * trusting a candidate the corpus already carries is circular: `fragezeich`
    happily confirms `fragezeicha`.
  * `word_table`, 214,183 words, holds `fragezeich`, `chromosome` and `bäd`
    itself -- it was built with the same pipeline.

The way out is a parser that shares no machinery with the first. Stanza's
German lemmatiser is dictionary-first and trained on the UD treebanks;
spaCy's is an edit-tree model, which is the thing that predicts "replace -en
with -a" and never checks the result is a word. Where the two disagree, one
of them is wrong, and that is a list worth reading. It is not an answer:
choosing the correction still needs a person, because Konto/Konten,
Mechanismus/Mechanismen and Zeichen/Zeichen do not follow one rule.

Stanza runs at ~75 sentences a second on this machine and the corpus is
397,125, so the whole thing is an hour and a half. It is sampled instead, in
two parts: every sentence carrying a lemma of a shape already known to be
damaged, which is where the answer is densest, and a random draw, which is
the only part that can find a shape nobody has thought of yet.

Never `device="mps"`: Stanza's LSTMs run about seven times slower on it.
"""
from __future__ import annotations

import csv
import random
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path("experiment_results")

# Shapes already caught by hand, used only to aim the targeted half of the
# sample. Nothing is judged by them.
SUSPECT = (
    re.compile(r"[a-zäöüß]{4,}a$"),        # -en read as -a
    re.compile(r"[a-zäöüß]{3,}(ch|ung|ig)$"),
)


def pick(sentences, targeted: int, random_n: int, seed: int = 0) -> list:
    """Sentences to ask Stanza about: the suspicious ones, and a fair draw."""
    shaped, rest = [], []
    for s in sentences:
        keys = [u.key for u in s.units if u.kind == "lemma"]
        (shaped if any(p.search(k) for k in keys for p in SUSPECT)
         else rest).append(s)
    rng = random.Random(seed)
    rng.shuffle(shaped)
    rng.shuffle(rest)
    return shaped[:targeted] + rest[:random_n]


def compare(app, chosen, say=print) -> list[dict]:
    """(surface, what spaCy said, what Stanza said) wherever they differ."""
    import stanza                                   # noqa: PLC0415 — heavy

    import spacy                                    # noqa: PLC0415
    nlp = spacy.load("de_core_news_md")
    t = time.perf_counter()
    docs = list(nlp.pipe([s.text for s in chosen], batch_size=64))
    say(f"  spaCy: {len(docs):,} sentences ({time.perf_counter() - t:.0f}s)")
    # What the corpus actually holds, surface by surface. Raw spaCy plus the
    # fix table is not what the reader meets: the verb guard, the lookup
    # fallback and the corpus-majority vote all sit between, and the last of
    # those only runs during a full build. Measured the raw way, this file
    # reported 823 bad lemmas that the corpus scan had already shown gone --
    # it was auditing the model, not the thing built from it.
    settled: dict = {}
    for line in chosen:
        for unit in line.units:
            if unit.kind != "lemma":
                continue
            surf = line.surface_of(unit)
            if surf:
                settled[(line.text, surf.lower())] = unit.key

    pipe = stanza.Pipeline(lang="de", processors="tokenize,pos,lemma",
                           tokenize_pretokenized=True, download_method=None,
                           logging_level="ERROR")
    words = [[t.text for t in doc] for doc in docs]
    t = time.perf_counter()
    done = pipe([w for w in words if w])
    say(f"  stanza: {len(done.sentences):,} sentences "
        f"({time.perf_counter() - t:.0f}s)")

    disagree: Counter = Counter()
    suggests: dict = defaultdict(Counter)
    ours = [doc for doc, w in zip(docs, words) if w]
    del chosen  # `settled` is what the corpus said; the sentences are done with
    for doc, theirs in zip(ours, done.sentences):
        if len(doc) != len(theirs.words):
            continue                    # alignment lost; skip rather than guess
        for token, other in zip(doc, theirs.words):
            if token.pos_ not in ("NOUN", "PROPN", "ADJ", "VERB", "ADV"):
                continue
            mine = settled.get((doc.text, token.text.lower()))
            if mine is None:
                continue                # not a unit the corpus kept; nothing to judge
            yours = (other.lemma or "").lower()
            if yours and mine != yours:
                disagree[(token.text, mine)] += 1
                suggests[(token.text, mine)][yours] += 1
    rows = []
    for (surface, mine), n in disagree.most_common():
        best, agreed = suggests[(surface, mine)].most_common(1)[0]
        rows.append({"surface": surface, "spacy": mine, "stanza": best,
                     "times": n, "stanza_agreed": agreed})
    return rows


def run(app, targeted: int = 9000, random_n: int = 9000, say=print) -> list[dict]:
    sentences = list(app.corpus(strict=True))
    chosen = pick(sentences, targeted, random_n)
    say(f"  {len(sentences):,} sentences in the corpus · asking about "
        f"{len(chosen):,}")
    rows = compare(app, chosen, say=say)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "08-lemma-disagreements.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["surface", "spacy", "stanza", "times",
                                "stanza_agreed"])
        writer.writeheader()
        writer.writerows(rows)
    say(f"  {len(rows):,} surface/lemma pairs the two disagree on")
    say(f"    -> {path}")
    return rows


def main() -> None:
    import sys                                      # noqa: PLC0415

    from context import Application                  # noqa: PLC0415
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    run(Application(), targeted=n, random_n=n)


if __name__ == "__main__":
    main()
