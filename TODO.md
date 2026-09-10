# Todo

Work that is understood but not done. Each entry says what, why, what it is
worth, and what would go wrong — so it can be picked up cold.

## Build speed

`build-corpus` is 828s over 1,128 videos. It is not paid per video: adding a
video goes through `CorpusUpdater.catch_up`, which parses only what is new. A
full rebuild is needed only when the analyser rules change, so these matter
about once a month — but when they matter, they cost a quarter of an hour.

Measured 2026-09-10, 8 cores:

    subtitle correction   342s   single process, before spaCy starts
    spaCy parse + units   486s   4 workers parsing, parent extracting
    total                 828s

### 1. Parallelise the subtitle correction — worth ~280s

`MergeCorrector.correct` is called once per video from `BuildCorpusCommand`.
It is pure Python, no model and no network, and each video is independent. A
`ProcessPoolExecutor` over videos should take 342s to something near 50s on
eight cores.

The care needed is ordering: the corpus is written in list order and the
filter carries de-duplication state that depends on what it has already seen
(`SentenceFilter.apply`, then `split`). Collect the per-video results and
reassemble them in the original video order before filtering, or the
duplicate-detection changes which of two identical lines survives — and the
build stops being reproducible.

Verify by rebuilding twice and diffing `sentence_units` — the row count and
the distinct unit count must both be identical to the serial build.

### 2. NER — NOT a free win, do not simply disable it

The pipeline loads `tok2vec, tagger, morphologizer, parser, lemmatizer,
attribute_ruler, ner` and NER is typically 15-25% of parse time. It looks like
dead weight because the analyser only wants tags and lemmas.

It is not. `matcher/phrase_finder.py:215` reads `child.ent_type_ == "PER"` to
decide whether a dependent is a person, which decides whether a phrase matches.
Disabling NER changes which patterns are extracted — a corpus change dressed
as a speed-up, and one that would be found weeks later as patterns quietly
missing.

If it is worth doing, do it deliberately: replace the `ent_type_` test with
something that does not need the model (`pos_ in ("PRON", "PROPN")` is already
half of that condition), measure how many phrase matches move, and treat it as
an analyser change with its own rebuild.

### 3. Phrase extraction is serial — the real ceiling

`analyze_all` forks four workers for the parse and then runs `_units` and
phrase extraction in the parent, one Doc at a time. Parent CPU was 5:52
against ~1:47 per worker: the parent is the bottleneck, so a bigger
`batch_size` buys nothing. Moving extraction into the workers means shipping
`Doc`s or re-parsing there, and is the largest of these three by far.

## Vocabulary

### 4. Adjectives sitting in `function_words.txt`

`stressig`, `interessante`, `alt`, `fest`, `bereit`, `voll`, `übrig`, `pack`,
`all`, `namens` are in the closed-class file and are not closed-class. They are
therefore assumed known on the strength of a category they do not belong to.
`db/word_repo.function_words` selects by tag, so either the tags are wrong for
these or the tag set is too wide. Decide per word rather than by rule; there
are about ten.

### 5. `--from known` has never been run

The 739 entries of `known_words.txt` are an A1/A2 exam wordlist that arrived
with the project skeleton and has never been checked against this reader. 15
words are confirmed, 0 denied. Until a few hundred are answered there is no
way to tell whether the list is a good prior or fiction, and that answer
decides whether it is worth keeping at all.
