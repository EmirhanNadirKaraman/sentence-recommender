# TODO

Measured on the video-subtitle corpus (2,045 teachable sentences) unless
noted. Numbers are here so the reason for each item survives.

## The roadmap covers 5% of the corpus and stops

```
distinct units in corpus : 5,459
unknown at start         : 4,806
roadmap runs to          :   241 steps
never reached            : 4,565
sentences readable after :   317 of 2,045
```

The walk can only take a unit when it is the *sole* unknown in some sentence.
Once no sentence has exactly one unknown left it halts, and the remaining
4,565 units only ever appear alongside two or more others. Three ways out,
roughly in order of what they buy:

### 1. Run `fill-gaps` against a local model

Built for exactly this. It walks the roadmap replaying the known set, finds
units with no i+1 sentence, and asks the model for one — verifying each
candidate with the same analyser the corpus was built with and keeping it only
if its unknowns are exactly the target.

Blocked on `LLM_BASE_URL` and `LLM_MODEL` in `.env`. Never run against a real
model; tested only against a scripted client.

### 2. Add more videos

Coverage scales with corpus size, and steeply. Measured both ways:

```
subtitles only :  5% of unknown units reached,    317 of 2,045 sentences readable
everything     : 81% of unknown units reached, 246,337 of 257,636 readable
```

That gap is the real cost of leaving Tatoeba out. Its sentences read worse,
but 33,335 steps against 240 is not a small difference — worth revisiting if
the subtitle corpus stays this thin.

`python main.py add-video <id>` scrapes a video straight into the catalogue,
borrowing language-app's own scraper.

The **Blocked** page is the shopping list. It runs the walk to exhaustion and
ranks what is stranded by how often it appears, with the closest sentence and
what else is unknown in it. The *one word away* filter is the highest-value
subset: 543 units whose easiest sentence has exactly two unknowns, so a single
clip saying either one plainly unblocks both.

### 3. Let the walk take i+2 steps when the frontier empties

**Not in effect today.** The deck on the reading page shows sentences with
more than one unknown, labelled "Also new: …", but that is display only — the
*walk* still advances solely through strictly-i+1 steps and still halts at
241. Widening it is a separate change to `RoadmapBuilder`.

Cheap to add. It breaks the promise the whole thing is built on, so it wants
a deliberate decision rather than a default: probably a flag, and probably
only after the frontier is genuinely empty rather than as a general relaxation.

## Waiting on setup

- **`data/function_words.txt`** — 230 closed-class lemmas, unreviewed. The
  roadmap treats every one as known, so it currently starts slightly further
  along than it should. Strike what you do not know, then `build-roadmap`.
- **The local model** — unblocks both `fill-gaps` and
  `build-corpus subtitle --corrector llm`. Watch the fallback count on the
  first run; a high one means the prompt needs work, not the code.

## Known limitations

- **`weiß` stays split** between the colour and the form of *wissen*. Both
  readings are frequent and the corpus vote deliberately refuses to flatten a
  genuine ambiguity. Fixing it properly needs per-token context that the
  corpus-wide correction does not have.
- **Subtitles carry no English.** Translations come from Tatoeba pairs, so on
  a subtitles-only roadmap the cloze cards give you the German with a blank
  and no gloss.
- **LLM subtitle correction is unexercised.** Parsing, chunking, fallback and
  the content check are tested against a stub over real HTTP; whether a model
  returns good German is unknown.
