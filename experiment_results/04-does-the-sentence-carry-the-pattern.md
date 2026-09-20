# Does the sentence carry the pattern?

Numbers from `04-pattern-sense-judged.csv`, every row read by hand against the sentence; the rule column joined afterwards from a fresh parse. `04-pattern-sense-rule.csv` is the rule's effect over a fresh slice of the corpus. The two model arms are not run yet.

## What this tests

A pattern unit is the verb wearing the one blueprint the dictionary holds for it. This asks how often the sentence realises that blueprint, and how much of the rest a parse rule already catches.

The labelling rule, so a second judge can reproduce it: *frame* when the word is in the blueprint's sense and any slot it lacks is one the frame lets you drop (`sagen` with no recipient, `passieren` with no dative, `helfen` with no object); *other* when the missing slot is the one that carries the sense (`sterben` without `an`, `fliehen` without `vor`, `aussehen` without `nach`), or the word is in another sense or frame altogether (an auxiliary, a modal, `glauben` with a clause, `bedeuten` meaning signify); *construction* when the tokens belong to a multiword unit the dictionary does not list (`es gibt`, `auf jeden Fall`, `eine Rolle spielen`), whether or not the word's own sense is still visible inside it; *unclear* when the subtitle is too garbled to tell.

## Uniform over rows — what the corpus suffers

300 rows.

| verdict | rows | share |
|---|---|---|
| frame | 212 | 71% |
| other | 56 | 19% |
| construction | 30 | 10% |
| unclear | 2 | 1% |

| rule | rows | judge agreed |
|---|---|---|
| aux | 15 | 15 |
| modal | 11 | 11 |
| es_gibt | 4 | 4 |

Residue after the rule: 270 rows, of which 212 carry the frame (79%), 30 another sense of the same word, 26 a construction the dictionary lacks, 2 unclear.

## Panel of the heaviest patterns — what the dictionary suffers

150 rows.

| verdict | rows | share |
|---|---|---|
| frame | 107 | 71% |
| other | 30 | 20% |
| construction | 13 | 9% |
| unclear | 0 | 0% |

| rule | rows | judge agreed |
|---|---|---|
| aux | 3 | 3 |
| modal | 6 | 6 |
| es_gibt | 3 | 3 |

Residue after the rule: 138 rows, of which 107 carry the frame (78%), 21 another sense of the same word, 10 a construction the dictionary lacks, 0 unclear.

## Per pattern, on the panel

| pattern | frame | other | construction | unclear |
|---|---|---|---|---|
| `etw./jdn. (Akk) haben` | 0 | 3 | 0 | 0 |
| `etw. (Akk) können` | 0 | 3 | 0 | 0 |
| `jdm. (Dat) etw. (Akk) geben` | 0 | 0 | 3 | 0 |
| `jdm. (Dat) etw. (Akk) sagen` | 3 | 0 | 0 | 0 |
| `etw. (Akk) machen` | 2 | 1 | 0 | 0 |
| `all, alle` | 3 | 0 | 0 | 0 |
| `etw. (Akk) wollen` | 0 | 3 | 0 | 0 |
| `etw./jdn. (Akk) sehen` | 3 | 0 | 0 | 0 |
| `das Jahr` | 3 | 0 | 0 | 0 |
| `etw. (Akk) wissen` | 3 | 0 | 0 | 0 |
| `der Mensch` | 3 | 0 | 0 | 0 |
| `etw./jdn. (Akk) finden` | 2 | 1 | 0 | 0 |
| `das Video` | 3 | 0 | 0 | 0 |
| `etw. (Akk) tun` | 3 | 0 | 0 | 0 |
| `jdm. (Dat) stehen` | 0 | 3 | 0 | 0 |
| `mit jdm. / über etw./jdn. sprechen` | 3 | 0 | 0 | 0 |
| `das Beispiel` | 1 | 0 | 2 | 0 |
| `selbst, selber` | 3 | 0 | 0 | 0 |
| `die Zeit` | 2 | 0 | 1 | 0 |
| `das Land` | 3 | 0 | 0 | 0 |
| `etw. (Akk) bekommen` | 3 | 0 | 0 | 0 |
| `etw./jdn. (Akk) brauchen` | 2 | 1 | 0 | 0 |
| `jdm. (Dat) etw. (Akk) bedeuten` | 0 | 3 | 0 | 0 |
| `gern, gerne` | 3 | 0 | 0 | 0 |
| `nichts, nix` | 2 | 0 | 1 | 0 |
| `jdm. (Dat) passieren` | 3 | 0 | 0 | 0 |
| `der Tag` | 3 | 0 | 0 | 0 |
| `die Frage` | 3 | 0 | 0 | 0 |
| `der Mann` | 3 | 0 | 0 | 0 |
| `jdm. (Dat) / etw. (Akk) glauben` | 0 | 3 | 0 | 0 |
| `die Frau` | 3 | 0 | 0 | 0 |
| `etw./jdn. (Akk) lassen` | 1 | 2 | 0 | 0 |
| `jdm. (Dat) etw. (Akk) schreiben` | 3 | 0 | 0 | 0 |
| `nach etw. aussehen` | 0 | 3 | 0 | 0 |
| `die Leute` | 3 | 0 | 0 | 0 |
| `die Partei` | 3 | 0 | 0 | 0 |
| `jdm. (Dat) etw. (Akk) zeigen` | 2 | 1 | 0 | 0 |
| `das Leben` | 2 | 0 | 1 | 0 |
| `das Kind` | 3 | 0 | 0 | 0 |
| `etw./jdn. (Akk) nehmen` | 1 | 0 | 2 | 0 |
| `jdm. (Dat) etw. (Akk) bringen` | 1 | 0 | 2 | 0 |
| `das Problem` | 3 | 0 | 0 | 0 |
| `der Fall` | 2 | 0 | 1 | 0 |
| `der Herr` | 3 | 0 | 0 | 0 |
| `das Thema` | 3 | 0 | 0 | 0 |
| `jdm. (Dat) gehören` | 0 | 3 | 0 | 0 |
| `etw./jdn. (Akk) kennen` | 3 | 0 | 0 | 0 |
| `das Geld` | 3 | 0 | 0 | 0 |
| `jdm. (Dat) helfen` | 3 | 0 | 0 | 0 |
| `lange, lang` | 3 | 0 | 0 | 0 |

## What the rule refuses, over a fresh slice

10,000 sentences, 10,903 verb pattern rows the old matcher would have emitted; the rule refuses 2,122 (19.5%) — 1,099 auxiliaries, 1,023 modals — and routes 349 more to `es gibt`.

An estimate, not the rebuild: the rows are re-derived here by looking each verb token's lemma up, which is the matcher's exact path but not its fuzzy fallback or its multi-token phrase. The number the corpus will actually lose is one query after `build-corpus subtitle` — `count(*)` of pattern rows against the 603,624 there today.

| pattern | rows | refused | rerouted |
|---|---|---|---|
| `etw./jdn. (Akk) haben` | 1666 | 1098 (66%) | 0 (0%) |
| `etw. (Akk) können` | 837 | 783 (94%) | 0 (0%) |
| `jdm. (Dat) etw. (Akk) geben` | 432 | 0 (0%) | 349 (81%) |
| `etw. (Akk) machen` | 404 | 0 (0%) | 0 (0%) |
| `jdm. (Dat) etw. (Akk) sagen` | 392 | 0 (0%) | 0 (0%) |
| `etw. (Akk) wollen` | 304 | 235 (77%) | 0 (0%) |
| `etw./jdn. (Akk) sehen` | 205 | 0 (0%) | 0 (0%) |
| `etw. (Akk) wissen` | 154 | 0 (0%) | 0 (0%) |
| `etw./jdn. (Akk) finden` | 134 | 0 (0%) | 0 (0%) |
| `etw. (Akk) tun` | 127 | 0 (0%) | 0 (0%) |
| `jdm. (Dat) stehen` | 107 | 0 (0%) | 0 (0%) |
| `etw. (Akk) bekommen` | 107 | 0 (0%) | 0 (0%) |
| `mit jdm. / über etw./jdn. sprechen` | 98 | 0 (0%) | 0 (0%) |
| `jdm. (Dat) etw. (Akk) bedeuten` | 90 | 0 (0%) | 0 (0%) |
| `etw./jdn. (Akk) brauchen` | 90 | 0 (0%) | 0 (0%) |
| `jdm. (Dat) passieren` | 81 | 0 (0%) | 0 (0%) |
| `etw./jdn. (Akk) lassen` | 77 | 0 (0%) | 0 (0%) |
| `jdm. (Dat) etw. (Akk) bringen` | 74 | 0 (0%) | 0 (0%) |
| `nach etw. aussehen` | 70 | 0 (0%) | 0 (0%) |
| `jdm. (Dat) / etw. (Akk) glauben` | 66 | 0 (0%) | 0 (0%) |

## Constructions the labels named

What the sentence carried instead, where the judge named it — the candidates a discovery pass would have to propose:

- `es gibt` × 7
- `vor allem` × 3
- `eine Rolle spielen` × 2
- `auf keinen Fall` × 2
- `zum Beispiel` × 2
- `Stand (Datum)` × 1
- `Gott bewahre` × 1
- `oh mein Gott` × 1
- `wie gesagt` × 1
- `was weiß ich` × 1
- `es handelt sich um` × 1
- `eine Menge (a lot)` × 1
- `Geschichte schreiben` × 1
- `auf jeden Fall` × 1
- `im Gegenteil` × 1
- `nach Hause` × 1
- `Rücksicht nehmen auf` × 1
- `jdm. einen Antrag machen` × 1
- `Krieg führen` × 1
- `oh Gott` × 1
- `sich einen Begriff von etw. machen` × 1
- `vielen Dank` × 1
- `es tut mir leid` × 1
- `einen Weg einschlagen` × 1
- `auf die Straße gehen` × 1
- `es wird Zeit` × 1
- `das wird nichts` × 1
- `ums Leben kommen` × 1
- `etw. zur Kenntnis nehmen` × 1
- `Platz nehmen` × 1
- `etw. auf den Markt bringen` × 1
- `etw. in seine Gewalt bringen` × 1
