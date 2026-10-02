"""Are separable verbs put back together? The claim this re-derives.

`steht … auf` is one word, `aufstehen`, and a pipeline that reads tokens one
at a time emits two: the bare stem and a loose particle. That is not a small
error. It puts `stehen` in front of `aufstehen`, `fangen` (to catch) in front
of `anfangen`, and `willigen`, which is not a word, in front of `einwilligen`.

Getting a prefix back onto its verb is three stages, and they fail for
different reasons, so a single percentage hides which one is being talked
about. This counts all three:

  1. The tagger says a token is a separated verb prefix (`PTKVZ`).
  2. The parser attaches it to its verb (`svp`).
  3. The analyser folds the two into one unit.

Stage 3 is the one this project owns, and it is what "unjoined particles 17%
-> 1%" (commit 91135a2) measured: of the prefixes the parser hands over, the
share left loose. Stages 1 and 2 are the parser's, measured here to say what
the ceiling is -- a prefix the parser never attaches cannot be folded by
anything downstream, and over a sample taken on 2026-09-20 that was 68 of 447,
most of them the tagger calling an adverb a particle.

Read off the built corpus rather than a fresh parse. The units a sentence ends
up with are the product of the whole stack -- the verb guard, the lookup
fallback, the hand tables, the corpus-wide majority vote -- and a measurement
taken from `analyze_all`, or from spaCy alone, is measuring a component and
has been wrong here before for exactly that reason.

Run: `PYTHONPATH=. .venv/bin/python experiments/separable_verbs.py [sample]`
"""
from __future__ import annotations

import random

SAMPLE = 5000
SEED = 0


def run(app, sample: int = SAMPLE, seed: int = SEED) -> dict:
    analyzer = app.analyzer
    nlp = analyzer.matcher.nlp
    table = analyzer.verb_lemmas

    def joined(token, particle) -> str:
        """The verb the two halves spell, or "" where they spell nothing.

        The same three readings of the stem the fold itself tries, weakest
        last: a tagger that has called an imperative a noun gives a noun's
        lemma, and `Räum` -> `räum` makes `aufräum`, which is not a word. The
        test is on the *combined* form, so a prefix the dictionary does not
        join to this verb is not counted against the fold -- `dabei` under
        `unterstützen` is a parse error, not a fold that failed.
        """
        head = token.text.lower()
        prefix = particle.lemma_.lower()
        for stem in (analyzer._verb_lemma(token),
                     table.get(head, ""), head + "en"):
            if stem and table.is_lemma(prefix + stem):
                # A stem carrying a prefix already spells nothing with another.
                return "" if analyzer._already_prefixed(stem) else prefix + stem
        return ""

    rows = [s for s in app.corpus(strict=True) if s.text]
    random.Random(seed).shuffle(rows)
    by_text = {s.text: s for s in rows[:sample]}

    claimed = attached = real = folded = split = vanished = 0
    loose: list[tuple[str, str, str]] = []
    spurious: list[tuple[str, str, str]] = []
    unattached: list[tuple[str, str]] = []
    for doc in nlp.pipe(list(by_text), batch_size=500,
                        n_process=app.settings.analysis_processes):
        sentence = by_text.get(doc.text)
        if sentence is None:
            continue
        keys = {u.key.lower() for u in sentence.units}
        for token in doc:
            # Stage 1: the tagger's claim that this is a separated prefix.
            if token.tag_ != "PTKVZ":
                continue
            claimed += 1
            # Stage 2: the parser hanging it under its verb.
            if token.dep_ != "svp":
                unattached.append((token.text, doc.text[:60]))
                continue
            attached += 1
            # Stage 3: did the corpus record the two as one unit? Only where
            # the two halves spell a verb the dictionary knows -- otherwise
            # the parser has attached something that is not a prefix, and
            # refusing to fold it is the right answer, not a miss.
            want = joined(token.head, token)
            if not want:
                spurious.append((token.lemma_.lower(),
                                 token.head.lemma_.lower(), doc.text[:60]))
                continue
            real += 1
            # Not equality: a reflexive separable verb is carried as a frame,
            # so `Stellt euch vor` ends up under `sich (Akk) etw. vorstellen`
            # and not under `vorstellen` alone. The fold worked in both; what
            # it means to have failed is that no unit mentions the combined
            # verb at all, and the bare stem is sitting there instead.
            if any(want in key for key in keys):
                folded += 1
            elif token.head.lemma_.lower() in keys:
                # The defect this is about: the stem kept, the prefix lost.
                split += 1
                if len(loose) < 12:
                    loose.append((want, "stem without its prefix",
                                  doc.text[:58]))
            else:
                # Neither half is a unit, so nothing was separated -- the verb
                # produced no unit at all. A lemma that failed, not a fold that
                # did, and counting it here would flatter or damn the fold for
                # something it never saw.
                vanished += 1
                if len(loose) < 12:
                    loose.append((want, "no unit for the verb at all",
                                  doc.text[:58]))
    return {"sentences": len(by_text), "claimed": claimed,
            "attached": attached, "real": real, "folded": folded,
            "split": split, "vanished": vanished,
            "loose": loose, "unattached": unattached, "spurious": spurious}


def report(found: dict, say=print) -> None:
    n, claimed = found["sentences"], found["claimed"]
    attached, folded = found["attached"], found["folded"]
    say(f"  {n:,} sentences from the built corpus\n")
    say(f"  1. tagged a separated prefix (PTKVZ) ... {claimed:,}")
    if not claimed:
        return
    missed = claimed - attached
    say(f"  2. the parser attached to its verb .... {attached:,} "
        f"({attached / claimed:.1%}) · {missed:,} left unattached")
    if not attached:
        return
    real = found["real"]
    say(f"  3. the halves spell a verb the table knows {real:,} "
        f"({real / attached:.1%}) · {attached - real:,} spell nothing")
    if not real:
        return
    say(f"  4. the corpus folded them into one unit  {folded:,} "
        f"({folded / real:.1%})")
    split, vanished = found["split"], found["vanished"]
    say(f"     of the rest, stem kept without its prefix  {split:,}")
    say(f"     and no unit for the verb at all ........... {vanished:,}")
    say(f"\n  unjoined -- the stem kept and the prefix lost, over the prefixes")
    say(f"  that really are separable verbs: {split / real:.1%}")
    say("  (the figure commit 91135a2 reports as 17% -> 1.0%)")
    if found["loose"]:
        say("\n  still unjoined:")
        for prefix, stem, text in found["loose"][:6]:
            say(f"    {prefix} + {stem} — {text}")


def main() -> None:
    import sys                                        # noqa: PLC0415

    from context import Application                   # noqa: PLC0415
    n = int(sys.argv[1]) if len(sys.argv) > 1 else SAMPLE
    report(run(Application(), sample=n))


if __name__ == "__main__":
    main()
