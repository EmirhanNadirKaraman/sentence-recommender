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

### 3. Let the walk take i+2 steps when the frontier empties  *(measured; not worth it)*

Written when the walk halted at 241 steps of 4,806 unknown units, where a
relaxation would have been the difference between a roadmap and a stub.
Option 2 above happened instead: the corpus went from 2,045 sentences to
115,461, and the strict walk now reaches 2,792 goals of 4,014.

Measured on that corpus, taking a sentence with two unknowns once no
sentence has one — and only where both unknowns are goals, since pairing a
goal with a word the walk will never teach is not a step the reader can
take:

```
reached by i+1 alone     2,792 goals
reached allowing pairs   2,861 goals   (+69, 2.5%)
still stranded             810         (252 never said in the corpus at all)
```

2,861 is exactly the ceiling — the goals that appear in any sentence free of
strangers — so pairs close the whole remaining gap and the whole remaining
gap is 69 goals. That is a poor price for breaking the promise the reading
page makes, plus a column on `roadmap`, a mode on the builder and a flag.

The same effort spent on strangers is worth more and costs no promise. 741
strangers are the single thing standing between some goal and an i+1
sentence, and the top of that list is not vocabulary — `kannstn`,
`brauchsen`, `beispielsätz`, `studierend` are lemmatiser slips, `nächster`,
`letzter`, `besonderer` are inflections that should reduce:

```
top  50 strangers fixed -> 87 goals unblocked
top 250 strangers fixed -> 219
top 500 strangers fixed -> 349
```

If it is ever built anyway: `RoadmapStep.also`, a `--pairs` flag, engaged
only once the frontier is genuinely empty, both units required to be goals,
and the page saying "two new things here" rather than claiming one.

## Waiting on setup

- **`data/function_words.txt`** — 230 closed-class lemmas, unreviewed. The
  roadmap treats every one as known, so it currently starts slightly further
  along than it should. Strike what you do not know, then `build-roadmap`.
- **The local model** — unblocks both `fill-gaps` and
  `build-corpus subtitle --corrector llm`. Watch the fallback count on the
  first run; a high one means the prompt needs work, not the code.

## The cache knows what made it  *(done)*

`fingerprint.py` hashes everything that decides how a unit is derived — the
matcher, the analyser, `final_result.txt`, `lemma_overrides.txt`, and the
versions of spaCy and the German models — into a short digest. Every corpus
build is stamped with it in `build_meta`, and the resolved vocabulary in
`resolved.json` carries it alongside the file stamps, because the model
resolves those files and changing it changes every lemma while the files
themselves stay put.

Loading a corpus whose stamp no longer matches prints:

```
warning: corpus 'subtitle' was analysed by different rules (fingerprint
0df110bd…) — rebuild it with `python main.py build-corpus subtitle`
```

Whole files are hashed rather than the rules picked out of them, so editing
a comment raises a false alarm. That is the right way round: a warning you
can dismiss costs a second, a stale cache you cannot see cost this project
two afternoons.

## Trigram identity is not word identity

`_trustworthy` accepts a fuzzy match only at 1.00, on the assumption that a
perfect trigram score means the same word. It does not:

```
Die meisten Menschen …   ->  der Meister   fuzzy (1.00)
```

*meisten* and *Meister* have identical trigram sets, so the match passes the
floor and is emitted as a real unit. Every fuzzy match at 1.00 is trusted
this way, and nothing downstream can tell the difference between this and a
genuine hit. Worth measuring how many 1.00 matches are actually distinct
words before deciding what to do — a length check would catch this one, but
the honest fix may be to require an exact match for short words.

## The determiner half of `article_order` is dead code

`matcher/phrase_finder.py:article_order` picks which article to try first for
a noun, so that `das Steuer` (a helm) and `die Steuer` (a tax) do not collapse
into whichever the dictionary happens to list first. It reads the gender off
the noun, and then — supposedly — off the noun's determiner as a second
opinion:

```python
for child in token.children:
    if child.dep_ == "det":
        genders.extend(child.morph.get("Gender"))
```

**That loop never runs.** The German model uses the TIGER dependency scheme,
where a determiner attaches as `nk`, not `det`:

```
Die Leiter steht an der Wand.
   Die      DET   dep=nk   head=Leiter
   Leiter   NOUN  dep=sb   head=steht
```

`extract_german_logic` two hundred lines above knows this — it collects
children with `dep_ in ["det", "poss", "amod", "nk"]`. Only the new function
got it wrong.

Nothing is currently mis-resolved *because* of this: German nouns almost
always carry their own `Gender`, so the first source answers and the dead
fallback is never needed. It matters when a noun's morphology comes back
empty, where the article silently falls back to fixed `der, die, das` order
instead of asking the determiner sitting right next to it.

The fix is to accept `nk` alongside `det`. It changes how nouns are matched,
so it only takes effect after re-analysing the corpora:

```
python main.py build-corpus subtitle       # about two minutes
python main.py build-corpus tatoeba        # about four minutes
```

### It will not fix `die Leiter`

Worth writing down so nobody tries. In the sentence above, spaCy tags both the
noun and its article `Gender=['Masc']` — it has decided *Leiter* is the
manager, not the ladder, and propagated that to `Die`. Noun and determiner
agree and both are wrong, so there is no second opinion to consult. Reading
the determiner's *surface* instead ("die" implies feminine or plural) means
reasoning about case and number for every noun in the corpus to rescue one
word, and would guess wrong elsewhere. `die Leiter` stays stranded, and that
is the right trade.

## `de_core_news_lg` is not an upgrade  *(measured)*

The clipped forms — `hab`, `sag`, `geh`, `mach`, `hör`, `lass` — are absent
from spaCy's German lemma table, which is built from written wordlists that
carry `habe` and `sage` and none of the spoken contractions. The lemmatiser
is an `EditTreeLemmatizer`, trained rather than a lookup, so the model does
have an opinion; on these it declines to have one and returns the surface.

`lg` was tried on the assumption that a bigger model would know them:

```
form    want      sm      md      lg
hab     haben     hab     hab     habn
sag     sagen     sag     sag     sagn
lass    lassen    lass    lass    lassen
mach    machen    mach    mach    machen
lässt   lassen    lässt   lässt   lässt
hör     hören     hör     hör     hör
geh     gehen     geh     geh     geh
```

Two of seven right and two invented words, and the inventions are the
problem rather than the misses. An override fires only where the parser
admits defeat by returning the surface unchanged; `habn` is not that, so no
override could ever correct it and the bogus unit would be permanent. The
same guess breaks entries that have worked for months — `lg` gives `mussn`
and `mussen` where `md` gives `muss`.

Over a 757-verb-token sample, `md` returns a lemma the table has never heard
of 4.5% of the time and `lg` 3.4%, so `lg` is marginally tidier on the crude
count. It is the shape of the failure that decides it: `md` fails cleanly and
can be corrected, `lg` fails creatively and cannot.

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
- **A stored deck can outlive the sentences in it.** Each step of a roadmap
  carries the sentences that teach it, named by text alone. Extending a
  roadmap replays the stored steps and leaves their decks untouched, which is
  right while a corpus only ever grows — but it moves the stamp to the corpus
  that produced the extension, so decks written against the older one now sit
  under a stamp vouching for them. Harmless until a rebuild *drops* sentences;
  at that point the reading page can offer a sentence the corpus no longer
  holds, and "Fix its words" on it will not find it.
