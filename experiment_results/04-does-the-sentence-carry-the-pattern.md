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

## Arm: jev (jev-1.13.0)

450 rows, 139s, 302,146 input tokens.

| view | rows | precision@0.5 | recall@0.5 | p ≥ 0.9: right/n | p ≤ 0.1: right/n | 0.3–0.7 band |
|---|---|---|---|---|---|---|
| all | 450 | 91% | 90% | 32/32 | 30/30 | 153 |
| residue | 408 | 92% | 90% | 32/32 | 9/9 | 148 |

Precision and recall are of *frame* against everything else; the two calibration columns say, of the rows the judge was sure about, how many the label agreed with; the band is the rows it was not sure about, which is the number a person would still read.

| pattern (panel) | p per row → label |
|---|---|
| `all, alle` | 0.69→frame, 0.55→frame, 0.67→frame |
| `das Beispiel` | 0.51→const, 0.65→frame, 0.36→const |
| `das Geld` | 0.85→frame, 0.90→frame, 0.87→frame |
| `das Jahr` | 0.68→frame, 0.76→frame, 0.72→frame |
| `das Kind` | 0.80→frame, 0.67→frame, 0.69→frame |
| `das Land` | 0.87→frame, 0.91→frame, 0.78→frame |
| `das Leben` | 0.73→frame, 0.56→const, 0.59→frame |
| `das Problem` | 0.46→frame, 0.78→frame, 0.86→frame |
| `das Thema` | 0.81→frame, 0.60→frame, 0.71→frame |
| `das Video` | 0.93→frame, 0.77→frame, 0.87→frame |
| `der Fall` | 0.66→frame, 0.35→const, 0.67→frame |
| `der Herr` | 0.49→frame, 0.38→frame, 0.51→frame |
| `der Mann` | 0.60→frame, 0.69→frame, 0.96→frame |
| `der Mensch` | 0.76→frame, 0.67→frame, 0.54→frame |
| `der Tag` | 0.75→frame, 0.81→frame, 0.53→frame |
| `die Frage` | 0.88→frame, 0.77→frame, 0.89→frame |
| `die Frau` | 0.54→frame, 0.72→frame, 0.89→frame |
| `die Leute` | 0.59→frame, 0.92→frame, 0.80→frame |
| `die Partei` | 0.91→frame, 0.90→frame, 0.77→frame |
| `die Zeit` | 0.87→frame, 0.81→frame, 0.57→const |
| `etw. (Akk) bekommen` | 0.75→frame, 0.62→frame, 0.70→frame |
| `etw. (Akk) können` | 0.09→other, 0.08→other, 0.10→other |
| `etw. (Akk) machen` | 0.44→other, 0.68→frame, 0.42→frame |
| `etw. (Akk) tun` | 0.77→frame, 0.71→frame, 0.69→frame |
| `etw. (Akk) wissen` | 0.59→frame, 0.19→frame, 0.53→frame |
| `etw. (Akk) wollen` | 0.15→other, 0.23→other, 0.12→other |
| `etw./jdn. (Akk) brauchen` | 0.95→frame, 0.14→other, 0.92→frame |
| `etw./jdn. (Akk) finden` | 0.83→frame, 0.85→frame, 0.79→other |
| `etw./jdn. (Akk) haben` | 0.13→other, 0.05→other, 0.21→other |
| `etw./jdn. (Akk) kennen` | 0.84→frame, 0.72→frame, 0.66→frame |
| `etw./jdn. (Akk) lassen` | 0.13→other, 0.64→frame, 0.60→other |
| `etw./jdn. (Akk) nehmen` | 0.21→const, 0.16→const, 0.45→frame |
| `etw./jdn. (Akk) sehen` | 0.90→frame, 0.73→frame, 0.13→frame |
| `gern, gerne` | 0.69→frame, 0.79→frame, 0.78→frame |
| `jdm. (Dat) / etw. (Akk) glauben` | 0.12→other, 0.47→other, 0.12→other |
| `jdm. (Dat) etw. (Akk) bedeuten` | 0.13→other, 0.51→other, 0.14→other |
| `jdm. (Dat) etw. (Akk) bringen` | 0.13→const, 0.14→const, 0.47→frame |
| `jdm. (Dat) etw. (Akk) geben` | 0.66→const, 0.21→const, 0.09→const |
| `jdm. (Dat) etw. (Akk) sagen` | 0.24→frame, 0.65→frame, 0.78→frame |
| `jdm. (Dat) etw. (Akk) schreiben` | 0.70→frame, 0.64→frame, 0.56→frame |
| `jdm. (Dat) etw. (Akk) zeigen` | 0.86→frame, 0.35→frame, 0.12→other |
| `jdm. (Dat) gehören` | 0.09→other, 0.14→other, 0.07→other |
| `jdm. (Dat) helfen` | 0.90→frame, 0.70→frame, 0.92→frame |
| `jdm. (Dat) passieren` | 0.26→frame, 0.61→frame, 0.63→frame |
| `jdm. (Dat) stehen` | 0.24→other, 0.40→other, 0.06→other |
| `lange, lang` | 0.81→frame, 0.79→frame, 0.69→frame |
| `mit jdm. / über etw./jdn. sprechen` | 0.30→frame, 0.12→frame, 0.23→frame |
| `nach etw. aussehen` | 0.39→other, 0.69→other, 0.68→other |
| `nichts, nix` | 0.87→frame, 0.62→const, 0.72→frame |
| `selbst, selber` | 0.75→frame, 0.75→frame, 0.66→frame |



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
