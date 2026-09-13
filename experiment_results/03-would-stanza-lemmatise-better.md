# Would Stanza lemmatise better than spaCy?

Numbers from `03-lemmatisers.csv`, one row per run. Per-token working in
`03-lemmatisers-tokens.csv.gz`; every disagreement with its sentence in
`03-lemmatisers-disagreements.csv`; the correction files replayed in
`03-lemmatisers-targeted.csv`. Rows are comparable only within a
`spacy_model`/`stanza` version pair.

## What this tests

The corpus is lemmatised by `de_core_news_md` plus a repair layer that grew
one failure at a time (`corpus/analyzer.py`). Stanza's German models — what
`spacy-stanza` wraps — are trained on the UD treebanks with a
dictionary-first lemmatiser. This asks whether they natively get right what
the repair layer patches by hand, and what they get wrong instead.

Stanza runs here over spaCy's own tokens, not through `spacy-stanza`. The
wrapper's lemmas are Stanza's either way, but its tokeniser expands `zum`
into `zu dem`, so token streams stop being one-to-one, and it labels
dependencies in UD terms where the matcher reads TIGER's (`oa`, `da`, `nk`,
`svp`). Feeding Stanza spaCy's tokens is also the only integration that
leaves the matcher untouched; the *own tokens* row measures what that costs.

## Speed

| pipeline | sentences / s (one process) |
|---|---|
| spaCy md, raw | 274.4 |
| Stanza default, spaCy tokens | 70.3 |
| Stanza default, own tokens | 58.9 |
| Stanza accurate, spaCy tokens | 26.4 |

Stanza's models are LSTMs; on this machine Metal (MPS) is seven times slower
than the CPU, so these are CPU figures, one process each. **Taken on a loaded
machine** — a `build-roadmap` ran throughout — so, as `TODO.md` warns of every
timing here, trust the ratios before the absolutes: a quiet probe beforehand
gave spaCy 423 and Stanza 76 sentences/s, the same 5–6× apart.

A rebuild does not run one process. `build-corpus` gives spaCy four workers,
which the README measures at about 700 sentences/s over the Tatoeba build.
Stanza under workers, steady state after each has loaded its models:

| Stanza workers | sentences / s, steady | start-up (s) | sentences / s incl. start-up |
|---|---|---|---|
| 1 | 57.6 | 4.8 | 44.2 |
| 2 | 71.3 | 5.9 | 49.0 |
| 4 | 67.2 | 9.5 | 42.0 |

Torch already spreads one Stanza process over several cores, so a second
process adds a fifth and a fourth adds nothing — the ceiling on this machine
is about 71 sentences/s however the work is
split (thread-per-worker tuning untested). Against the corpus's 314,929
teachable sentences that is about 74 minutes for a full rebuild, to
spaCy's 7.

## The yardsticks

8,000 random teachable sentences (6,000 subtitle,
2,000 transcript), 79,556 content tokens
(spaCy's view of which tokens are content: not punctuation, not a name,
number or foreign word). No ground truth; each column is an objective test.

*Not a word*: the lemma is written nowhere in the corpus and is neither a
form nor a lemma in spaCy's 355k-entry German table — the test
`data/lemma_fixes.txt` was built with. *Finite verb unreduced*: a token the
model itself tags as a finite or imperative verb, whose lemma is its own
surface and does not end in -en/-n. *Same lemma initial/mid*: surfaces seen
at least twice at the start of a sentence and twice elsewhere, counted
consistent when the majority lemma agrees — the `Hast du Zeit?` failure.
*Homograph*: the 29 nouns in `data/noun_verb_splits.txt`, tagged NN, whose
lemma kept its capital.

| lemma source | not a word | finite verb unreduced | same lemma initial/mid | homograph noun keeps capital | distinct lemmas |
|---|---|---|---|---|---|
| spaCy md, raw | 1.2% | 7.3% | 91.3% of 335 | 81.2% of 128 | 9178 |
| spaCy md + repair layer | 0.8% | 3.8% | 93.1% of 335 | 81.2% of 128 | 9033 |
| Stanza default, spaCy tokens | 0.8% | 0.4% | 93.7% of 335 | 100.0% of 128 | 8750 |
| Stanza default, own tokens | 0.5% | 0.4% | 93.7% of 334 | 100.0% of 126 | 8392 |
| Stanza accurate, spaCy tokens | 1.0% | 0.6% | 91.0% of 335 | 100.0% of 128 | 8757 |

| tagger | initial word tagged NE | mid-sentence word tagged NE |
|---|---|---|
| spaCy md | 6.2% | 3.8% |
| Stanza default | 5.5% | 3.2% |
| Stanza accurate | 4.2% | 3.2% |

Stanza offers two lemmas joined by `|` (`denken|gedenken`, an HDT habit)
for 0.1% of content tokens — the first is taken above — and a
pre-1996 spelling (`Abschluß`, `Tip`) for 0.2%. The taggers call
4.0% (spaCy) and 3.5% (Stanza) of word tokens a name: 1038
tokens are a name to spaCy alone and 558 to Stanza alone.

The two disagree on **7.1%** of content tokens, which touches
**48.6%** of sentences' lemma sets — but most of that is
function words, where the lemma is a convention (UD says `ich` for `mir`
and keeps `im` whole; spaCy says `mir` and `in`) and the word is in the
known set regardless. On the open classes — nouns, verbs, adjectives,
adverbs, the tokens that become vocabulary — they disagree on
**5.2%** (2,289 of 44,363). Stanza's accurate package agrees
with its default on 98.6% of content tokens. Given its own tokeniser,
Stanza aligns with spaCy's tokens on 98.9% of content tokens and gives the
same lemma on 98.6% of those — pretokenising costs it little.

Where the same surface gets different lemmas by position (most frequent first):

spaCy md + repair layer:

| surface | lemma when initial | lemma mid-sentence | seen |
|---|---|---|---|
| bin | bin | sein | 6+150 |
| einer | einer | ein | 2+131 |
| viele | viele | vieler | 19+100 |
| macht | macht | machen | 4+87 |
| hab | hab | haben | 4+78 |
| weiß | weiß | wissen | 5+67 |
| deutsche | deutsche | deutsch | 2+38 |
| stellen | stelle | stellen | 2+24 |

Stanza default, spaCy tokens:

| surface | lemma when initial | lemma mid-sentence | seen |
|---|---|---|---|
| dass | daß | dass | 25+444 |
| ihr | ihr | sie | 42+337 |
| sagen | sage | sagen | 9+135 |
| dich | dich | du | 3+127 |
| weiß | weiß | wissen | 5+67 |
| weiter | weit | weiter | 2+53 |
| wollen | wolle | wollen | 3+45 |
| ins | ins | ecser | 2+45 |

Both fail on the capitalised first word, differently. spaCy leaves the
finite verb (`Bin`, `Macht`, `Hab`); Stanza reaches for old spelling
(`Dass` → `daß`) or a first-person form of an infinitive (`Sagen wir` →
`sage`), and — in the override set below — leaves the clipped imperative
alone or calls it a noun (`Sag`, `Hör`, `Mach`, `Geh`, `Versuch`), which is
how spoken German starts a great many sentences.

## The correction files, replayed

Every row is a case spaCy once got wrong, so this can only say whether
Stanza needs the same patches — not whether it needs others. *overrides*
and *fixes* are corpus sentences holding the form; *goals* are bare words
with no sentence at all (the `lemmatise_each` path); *readme* the two
documented failures.

| set | rows | spaCy raw | spaCy + repair | Stanza default | Stanza accurate |
|---|---|---|---|---|---|
| overrides | 172 | 11 (6%) | 158 (92%) | 141 (82%) | 134 (78%) |
| fixes | 64 | 0 (0%) | 64 (100%) | 61 (95%) | 62 (97%) |
| goals | 18 | 15 (83%) | 15 (83%) | 15 (83%) | 16 (89%) |
| readme | 4 | 1 (25%) | 4 (100%) | 3 (75%) | 3 (75%) |

What Stanza still gets wrong on this set:

| set | form | should be | Stanza | Stanza acc. | spaCy + repair | sentence |
|---|---|---|---|---|---|---|
| overrides | Muss | müssen | Muss | Muss | müssen | Muss man ja. Aber Sie auch, wenn Sie so'n Job machen hier, d |
| overrides | Lass | lassen | laß | lassen | lassen | Lass gerne ein Abo da und gib mir einen Daumen nach oben. |
| overrides | lass | lassen | laß | laß | lassen | Ist heute anscheinend der lass es dir eine Lehre sein Tag. v |
| overrides | lass | lassen | laß | laß | lassen | Bitte lass meine Eltern endlich gehen. |
| overrides | lass | lassen | laß | laß | lassen | Okay, lass uns schnell zu Österreich. |
| overrides | Sag | sagen | sag | Sagen | sagen | Sag ihm, wer du wirklich bist! |
| overrides | Sag | sagen | Sag | Sag | sagen | Haha. Es ist ein Adjektiv. - Sag doch mal 'n Satz. |
| overrides | Hör | hören | Hör | Hör | hör | Hör auf die Vielleicht würdest du es ja auch gerne mal mit L |
| overrides | Hör | hören | Hör | Hör | hören | Gewöhn dir das ab! Hör auf damit! |
| overrides | Mach | machen | Mach | Mach | mach | Mach ihr schaff Fleisch aus dir. |
| overrides | Geh | gehen | geh | gehen | geh | Geh nur versteck dich irgendwo. |
| overrides | Versuch | versuchen | Versuch | Versuch | versuch | Versuch' das eigentlich zu vermeiden, weil ich's selbst unan |

## Stanza as an oracle for the correction files

Whichever way the runtime question goes, Stanza's answers can be mined
offline. A candidate override is a verb the analyser still hands back
unreduced where Stanza gives an attested infinitive; a candidate fix is a
lemma nobody has written beside one somebody has. 205 override
lines and 110 fix lines in this sample alone, all in
`03-lemmatisers-candidates.csv`. Every one needs reading before it goes in a
file: the same test would have proposed `sein -> mein`.

| kind | analyser says | Stanza says | times | example |
|---|---|---|---|---|
| override | würd | werden | 12 | ich würd' schon sagen, nicht spießiger, I'd say so, not more |
| override | verlinkt | verlinken | 9 | Mehr zu den technischen Details in einem eigenen Video dazu, |
| override | danke | danken | 6 | Herr Habeck, vielleicht. (Rednerwechsel) Ja, danke. |
| override | wär | sein | 6 | Wie wär’s, wenn du was Praktischeres mitbringst? |
| override | freu | freuen | 5 | Wenn ihr Lust habt, freu ich mich selbstverständlich, wenn i |
| override | wüsste | wissen | 5 | Wenn ich das wüsste, wären wir bestimmt der Lösung dieses Pr |
| override | find | finden | 5 | Und äh… und äh… das ist also dieser, dieser Hilfegedanke, de |
| override | warst | sein | 4 | Du warst ein paar Tage im Koma. |
| override | isst | essen | 4 | Je schneller du isst, umso früher sind wir fertig. |
| override | darfst | dürfen | 4 | Du darfst die Leitung nicht loslassen. |
| override | bräuchte | brauchen | 4 | Denn dafür bräuchte man erst mal Geld, um Spieler zu kaufen. |
| override | frag | fragen | 3 | Ich frag: „Wo geht's zum Bahnhof?“, sie sagt: „Je ne sais pa |
| override | tu | tun | 3 | Bitte tu das nicht, Maria. |
| override | gefällt | gefallen | 3 | Ich hoffe Nina gefällt mein Outfit. |
| override | komm | kommen | 3 | Nun komm, Go. Na los, geh schlag zurück. |

## Adjudication

200 random disagreements on open-class tokens, read by hand (judge: claude-opus-5). `st` means Stanza was right, `md` the analyser, `both` that either reading is defensible — mostly a convention the two treebanks differ on — and `neither` that both were wrong. Every row, with its sentence and the reason, is in `03-lemmatisers-judged.csv`.

| verdict | count | share |
|---|---|---|
| st | 93 | 46% |
| md | 50 | 25% |
| both | 47 | 24% |
| neither | 10 | 5% |

Stanza was right because spaCy + repair:

| kind | rows | examples |
|---|---|---|
| left unreduced | 52 | kollidierten → kollidieren (not kollidierten); wehzutun → wehtun (not wehzutun); glaub → glauben (not glaub) |
| invented lemma | 27 | Verben → Verb (not verbe); willst → wollen (not willen); zahl → zahlen (not zahln) |
| wrong reading | 11 | Neues → Neu (not neue); genervt → nerven (not genervt); liebst → lieben (not liebst) |
| foreign word | 1 | expensive → expensive (not expensiv) |
| dialect form | 1 | issä → essen (not issä) |
| sentence-initial | 1 | Scheitert → scheitern (not scheitert) |

spaCy + repair was right because Stanza:

| kind | rows | examples |
|---|---|---|
| wrong reading | 14 | Bitten → bitten (not Bitte); spitzen → spitzen (not spitz); Verrückte → verrückt (not Verrückte) |
| old spelling | 8 | Prozess → prozess (not Prozeß); Abschluss → abschluss (not Abschluß); Anlass → anlass (not Anlaß) |
| particle as verb/noun | 7 | ne → ne (not ein); Danke → danke (not Dank); danke → danke (not danken) |
| 's contraction | 4 | geht's → gehen (not gehe'en); geht's → gehen (not gehe'en); Let's → let's (not Let') |
| left unreduced | 4 | geheimnisvollen → geheimnisvoll (not geheimnisvollen); abstruse → abstrus (not abstruse); allererste → allererster (not allererste) |
| sentence-initial | 4 | Sagt → sagen (not sagt); Findet → finden (not Findet); Willst → wollen (not willen) |
| foreign word | 3 | take → take (not taken); written → written (not wreiten); well → well (not wellen) |
| stem variant | 3 | böse → böse (not bös); Weihnachten → weihnachten (not Weihnacht); böse → böse (not bös) |
| invented lemma | 2 | finsteren → finster (not finst); Zuschauen → Zuschauen (not Zuschaue) |
| name | 1 | Anderten → anderten (not Andert) |

Both defensible:

| kind | rows | examples |
|---|---|---|
| convention | 29 | letzter / letzt; erster / erst; zweiter / zweit |
| both exist | 8 | mutant / Mutante; ’s / 's; fakt / Faktum |
| lexicalised comparative | 6 | früh / früher; weiter / weit; öfter / oft |
| participial adjective | 4 | erkältet / erkälten; begeistert / begeistern; beeindrucken / beeindruckt |

## What it means

**Yes, measurably, on the words that matter — but not as a pipeline swap.** A finite verb comes back unreduced 0.4% of the time under Stanza against 3.8% after the repair layer, and 7.3% before it: the failure the whole two-pass design exists for, `Hast du Zeit?`, is one Stanza's dictionary rarely makes. The noun/verb homographs keep their capital 100% of the time against 81%. Non-word lemmas come out level (0.8% against 0.8%), but for different reasons, as the adjudication shows.

Read by hand, Stanza was right in 93 of 200 open-class disagreements and the analyser in 50; 47 were conventions and 10 were wrong both ways. Scaled back to the sample, that is a net 1.1% of open-class tokens moved from wrong to right (give or take 0.4 points: it rests on 200 verdicts), in roughly 5% of sentences — and a wrong lemma in a sentence is a phantom unknown that keeps it out of the roadmap. The shape of the two error sets is the larger finding. Stanza wins the long tail — plurals, participles, clipped and second-person verbs left unreduced, compounds truncated to non-words — which is exactly what `lemma_overrides.txt` and `lemma_fixes.txt` chase one line at a time, and the sample turned up new inventions (`pfannkuch` beside the listed `pfannkuche`, `willen`, `traumus`) that the files do not yet hold. spaCy wins a short list of *systematic* Stanza habits: pre-1996 spellings, an inheritance of 1990s newspaper training text (`Abschluß`, `Rußland`, `Tip`), particles read as verbs or nouns (`danke` → `Dank`, `bitte` → `bitten`, `ne` → `ein`), the spoken `'s` contraction (`geht's` → `gehe'en`), `weißt` → `weißen`, and the capitalised clipped imperative that opens so much spoken German (`Sag`, `Hör`, `Mach`, `Geh`; `Lass` → `laß`). Each of those is a rule or a twenty-line table — the imperatives are already in `lemma_overrides.txt`, which is surface-keyed and would go on applying — and the long tail is not.

It costs 3.9× the time process for process, and more in practice, because spaCy scales across `build-corpus`'s workers and Stanza does not: about 71 sentences/s is the ceiling here however the work is split, so a full teachable rebuild is roughly 74 minutes against spaCy's 7, and every `add-video` pays the same ratio. The `default_accurate` package is slower again (26 sentences/s) and no better — worse on the override cases and prone to its own inventions (`Gibst` → `libsten`) — so there is nothing to buy there.

Three ways to take it, in order of how much they touch:

1. **Oracle.** Run Stanza offline over the corpus, keep spaCy at runtime, and let the disagreements write the correction files: 205 override lines and 110 fix lines from this sample alone, each needing a glance before it goes in (`danke → danken` is on the list, and must not go in). Zero runtime cost, and it turns a hand-hunt into a list.
2. **Lemma source.** Keep spaCy's tokeniser, tagger and parser — the matcher reads TIGER labels and would break under UD's — and take the lemma from Stanza run pretokenised over spaCy's tokens, which this experiment shows costs it nothing (98.6% agreement with its own tokenisation). Then normalise ß-spellings, keep the particle and contraction overrides, and re-resolve the vocabulary files, because the lemma space changes (`letzt` for `letzter`, `ich` for `mir`, `im` kept whole).
3. **`spacy-stanza` wholesale.** Not recommended: it brings Stanza's tokeniser, with its multiword expansion, and UD dependency labels into a matcher written for TIGER's.

## History

| run | sentences | non-word md+repair | non-word Stanza | unreduced md+repair | unreduced Stanza | disagree | Stanza sent/s | versions |
|---|---|---|---|---|---|---|---|---|
| 2026-09-13 00:41 | 8000 | 0.008 | 0.008 | 0.0375 | 0.0035 | 0.0714 | 70.3 | 1.14.0 |

