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

## Arm: jev (jev-1.13.0), question: frame — does the sentence realise the blueprint

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


## Arm: jev (jev-1.13.0), question: plain — is this the word itself, not a fixed expression or another word

448 rows, 139s, 312,019 input tokens.

| view | rows | precision@0.5 | recall@0.5 | p ≥ 0.9: right/n | p ≤ 0.1: right/n | 0.3–0.7 band |
|---|---|---|---|---|---|---|
| all | 448 | 95% | 93% | 92/92 | 2/2 | 151 |
| residue | 406 | 96% | 92% | 74/74 | 2/2 | 145 |

Precision and recall are of *good example* against everything else; the two calibration columns say, of the rows the judge was sure about, how many the label agreed with; the band is the rows it was not sure about, which is the number a person would still read.

| pattern (panel) | p per row → label |
|---|---|
| `all, alle` | 0.80→frame, 0.65→frame, 0.82→frame |
| `das Beispiel` | 0.64→const, 0.65→frame, 0.52→const |
| `das Geld` | 0.88→frame, 0.96→frame, 0.74→frame |
| `das Jahr` | 0.63→frame, 0.54→frame, 0.41→frame |
| `das Kind` | 0.69→frame, 0.58→frame, 0.54→frame |
| `das Land` | 0.91→frame, 0.89→frame, 0.57→frame |
| `das Leben` | 0.81→frame, 0.14→const, 0.61→frame |
| `das Problem` | 0.33→frame, 0.56→frame, 0.49→frame |
| `das Thema` | 0.81→frame, 0.32→frame, 0.59→frame |
| `das Video` | 0.92→frame, 0.54→frame, 0.75→frame |
| `der Fall` | 0.53→frame, 0.24→const, 0.86→frame |
| `der Herr` | 0.38→frame, 0.36→frame, 0.42→frame |
| `der Mann` | 0.56→frame, 0.46→frame, 0.95→frame |
| `der Mensch` | 0.55→frame, 0.50→frame, 0.57→frame |
| `der Tag` | 0.62→frame, 0.63→frame, 0.42→frame |
| `die Frage` | 0.93→frame, 0.72→frame, 0.95→frame |
| `die Frau` | 0.58→frame, 0.72→frame, 0.95→frame |
| `die Leute` | 0.88→frame, 0.96→frame, 0.60→frame |
| `die Partei` | 0.91→frame, 0.92→frame, 0.62→frame |
| `die Zeit` | 0.70→frame, 0.69→frame, 0.70→const |
| `etw. (Akk) bekommen` | 0.80→frame, 0.60→frame, 0.80→frame |
| `etw. (Akk) können` | 0.90→other, 0.96→other, 0.97→other |
| `etw. (Akk) machen` | 0.74→other, 0.72→frame, 0.71→frame |
| `etw. (Akk) tun` | 0.82→frame, 0.71→frame, 0.77→frame |
| `etw. (Akk) wissen` | 0.81→frame, 0.65→frame, 0.87→frame |
| `etw. (Akk) wollen` | 0.86→other, 0.89→other, 0.94→other |
| `etw./jdn. (Akk) brauchen` | 0.89→frame, 0.93→other, 0.85→frame |
| `etw./jdn. (Akk) finden` | 0.84→frame, 0.82→frame, 0.81→other |
| `etw./jdn. (Akk) haben` | 0.90→other, 0.88→other, 0.86→other |
| `etw./jdn. (Akk) kennen` | 0.85→frame, 0.84→frame, 0.87→frame |
| `etw./jdn. (Akk) lassen` | 0.06→other, 0.83→frame, 0.73→other |
| `etw./jdn. (Akk) nehmen` | 0.21→const, 0.30→const, 0.60→frame |
| `etw./jdn. (Akk) sehen` | 0.90→frame, 0.73→frame, 0.78→frame |
| `gern, gerne` | 0.79→frame, 0.78→frame, 0.85→frame |
| `jdm. (Dat) / etw. (Akk) glauben` | 0.87→other, 0.94→other, 0.97→other |
| `jdm. (Dat) etw. (Akk) bedeuten` | 0.94→other, 0.78→other, 0.91→other |
| `jdm. (Dat) etw. (Akk) bringen` | 0.62→const, 0.36→const, 0.85→frame |
| `jdm. (Dat) etw. (Akk) geben` | 0.84→const, 0.78→const, 0.76→const |
| `jdm. (Dat) etw. (Akk) sagen` | 0.46→frame, 0.65→frame, 0.79→frame |
| `jdm. (Dat) etw. (Akk) schreiben` | 0.80→frame, 0.80→frame, 0.75→frame |
| `jdm. (Dat) etw. (Akk) zeigen` | 0.67→frame, 0.78→frame, 0.43→other |
| `jdm. (Dat) gehören` | 0.07→other, 0.38→other, 0.14→other |
| `jdm. (Dat) helfen` | 0.77→frame, 0.96→frame, 0.60→frame |
| `jdm. (Dat) passieren` | 0.80→frame, 0.90→frame, 0.71→frame |
| `jdm. (Dat) stehen` | 0.88→other, 0.75→other, 0.91→other |
| `lange, lang` | 0.91→frame, 0.86→frame, 0.92→frame |
| `mit jdm. / über etw./jdn. sprechen` | 0.73→frame, 0.88→frame, 0.96→frame |
| `nach etw. aussehen` | 0.60→other, 0.72→other, 0.68→other |
| `nichts, nix` | 0.95→frame, 0.78→const, 0.89→frame |
| `selbst, selber` | 0.94→frame, 0.93→frame, 0.92→frame |


## Arm: jev (jev-1.13.0), question: guessable — could a reader who had every other word work this one out

100 rows, 32s, 53,596 input tokens.

| view | rows | precision@0.5 | recall@0.5 | p ≥ 0.9: right/n | p ≤ 0.1: right/n | 0.3–0.7 band |
|---|---|---|---|---|---|---|
| all | 100 | 87% | 88% | 0/0 | 0/0 | 55 |
| residue | 100 | 87% | 88% | 0/0 | 0/0 | 55 |

Precision and recall are of *guessable* against everything else; the two calibration columns say, of the rows the judge was sure about, how many the label agreed with; the band is the rows it was not sure about, which is the number a person would still read.

| pattern (panel) | p per row → label |
|---|---|
| `all, alle` | 0.79→frame, 0.76→frame |
| `das Beispiel` | 0.75→frame |
| `das Land` | 0.88→frame |
| `das Problem` | 0.65→frame |
| `der Herr` | 0.63→frame, 0.47→frame |
| `der Mensch` | 0.65→frame |
| `der Tag` | 0.76→frame, 0.56→frame |
| `die Leute` | 0.51→frame, 0.68→frame |
| `die Partei` | 0.74→frame |
| `etw. (Akk) bekommen` | 0.70→frame |
| `etw. (Akk) machen` | 0.49→frame, 0.50→frame |
| `etw. (Akk) tun` | 0.26→frame |
| `etw./jdn. (Akk) brauchen` | 0.86→frame |
| `etw./jdn. (Akk) kennen` | 0.66→frame |
| `etw./jdn. (Akk) nehmen` | 0.83→frame |
| `etw./jdn. (Akk) sehen` | 0.73→frame |
| `gern, gerne` | 0.70→frame, 0.58→frame |
| `jdm. (Dat) etw. (Akk) zeigen` | 0.70→frame |
| `jdm. (Dat) helfen` | 0.83→frame, 0.76→frame |
| `lange, lang` | 0.81→frame |
| `mit jdm. / über etw./jdn. sprechen` | 0.77→frame |
| `nichts, nix` | 0.73→frame, 0.60→frame |


## Arm: jev (jev-1.13.0), question: guessable as a rubric — nothing / a hint / gives it away, expected level scaled to 0–1

100 rows, 32s, 61,296 input tokens.

| view | rows | precision@0.5 | recall@0.5 | p ≥ 0.9: right/n | p ≤ 0.1: right/n | 0.3–0.7 band |
|---|---|---|---|---|---|---|
| all | 100 | 86% | 90% | 3/3 | 0/0 | 40 |
| residue | 100 | 86% | 90% | 3/3 | 0/0 | 40 |

Precision and recall are of *guessable* against everything else; the two calibration columns say, of the rows the judge was sure about, how many the label agreed with; the band is the rows it was not sure about, which is the number a person would still read.

| pattern (panel) | p per row → label |
|---|---|
| `all, alle` | 0.81→frame, 0.76→frame |
| `das Beispiel` | 0.86→frame |
| `das Land` | 0.94→frame |
| `das Problem` | 0.73→frame |
| `der Herr` | 0.74→frame, 0.40→frame |
| `der Mensch` | 0.71→frame |
| `der Tag` | 0.69→frame, 0.69→frame |
| `die Leute` | 0.52→frame, 0.71→frame |
| `die Partei` | 0.77→frame |
| `etw. (Akk) bekommen` | 0.73→frame |
| `etw. (Akk) machen` | 0.47→frame, 0.48→frame |
| `etw. (Akk) tun` | 0.10→frame |
| `etw./jdn. (Akk) brauchen` | 0.93→frame |
| `etw./jdn. (Akk) kennen` | 0.65→frame |
| `etw./jdn. (Akk) nehmen` | 0.89→frame |
| `etw./jdn. (Akk) sehen` | 0.83→frame |
| `gern, gerne` | 0.75→frame, 0.73→frame |
| `jdm. (Dat) etw. (Akk) zeigen` | 0.89→frame |
| `jdm. (Dat) helfen` | 0.85→frame, 0.77→frame |
| `lange, lang` | 0.91→frame |
| `mit jdm. / über etw./jdn. sprechen` | 0.76→frame |
| `nichts, nix` | 0.80→frame, 0.77→frame |


## Arm: local (unsloth/Qwen3.5-9B-GGUF), question: frame — does the sentence realise the blueprint

450 rows, 1304s.

| view | rows | precision@0.5 | recall@0.5 | p ≥ 0.9: right/n | p ≤ 0.1: right/n | 0.3–0.7 band |
|---|---|---|---|---|---|---|
| all | 450 | 82% | 82% | 71/72 | 4/5 | 163 |
| residue | 408 | 86% | 82% | 71/71 | 3/4 | 141 |

Precision and recall are of *frame* against everything else; the two calibration columns say, of the rows the judge was sure about, how many the label agreed with; the band is the rows it was not sure about, which is the number a person would still read.

| pattern (panel) | p per row → label |
|---|---|
| `all, alle` | 0.63→frame, 0.40→frame, 0.63→frame |
| `das Beispiel` | 0.77→const, 0.62→frame, 0.78→const |
| `das Geld` | 0.59→frame, 0.79→frame, 0.86→frame |
| `das Jahr` | 0.88→frame, 0.59→frame, 0.77→frame |
| `das Kind` | 0.85→frame, 0.85→frame, 0.72→frame |
| `das Land` | 0.87→frame, 0.84→frame, 0.72→frame |
| `das Leben` | 0.91→frame, 0.65→const, 0.53→frame |
| `das Problem` | 0.84→frame, 0.45→frame, 0.97→frame |
| `das Thema` | 0.77→frame, 0.38→frame, 0.69→frame |
| `das Video` | 0.92→frame, 0.76→frame, 0.75→frame |
| `der Fall` | 0.68→frame, 0.27→const, 0.84→frame |
| `der Herr` | 0.76→frame, 0.42→frame, 0.85→frame |
| `der Mann` | 0.90→frame, 0.74→frame, 0.60→frame |
| `der Mensch` | 0.80→frame, 0.82→frame, 0.79→frame |
| `der Tag` | 0.95→frame, 0.80→frame, 0.78→frame |
| `die Frage` | 0.81→frame, 0.82→frame, 0.85→frame |
| `die Frau` | 0.39→frame, 0.32→frame, 0.79→frame |
| `die Leute` | 0.86→frame, 0.76→frame, 0.68→frame |
| `die Partei` | 0.78→frame, 0.79→frame, 0.88→frame |
| `die Zeit` | 0.76→frame, 0.39→frame, 0.62→const |
| `etw. (Akk) bekommen` | 0.71→frame, 0.93→frame, 0.84→frame |
| `etw. (Akk) können` | 0.35→other, 0.49→other, 0.64→other |
| `etw. (Akk) machen` | 0.14→other, 0.96→frame, 0.46→frame |
| `etw. (Akk) tun` | 0.88→frame, 0.88→frame, 0.32→frame |
| `etw. (Akk) wissen` | 0.75→frame, 0.17→frame, 0.64→frame |
| `etw. (Akk) wollen` | 0.47→other, 0.92→other, 0.41→other |
| `etw./jdn. (Akk) brauchen` | 0.88→frame, 0.16→other, 0.80→frame |
| `etw./jdn. (Akk) finden` | 0.40→frame, 0.94→frame, 0.70→other |
| `etw./jdn. (Akk) haben` | 0.47→other, 0.49→other, 0.30→other |
| `etw./jdn. (Akk) kennen` | 0.87→frame, 0.82→frame, 0.82→frame |
| `etw./jdn. (Akk) lassen` | 0.48→other, 0.82→frame, 0.84→other |
| `etw./jdn. (Akk) nehmen` | 0.59→const, 0.76→const, 0.31→frame |
| `etw./jdn. (Akk) sehen` | 0.80→frame, 0.54→frame, 0.43→frame |
| `gern, gerne` | 0.81→frame, 0.84→frame, 0.96→frame |
| `jdm. (Dat) / etw. (Akk) glauben` | 0.67→other, 0.65→other, 0.47→other |
| `jdm. (Dat) etw. (Akk) bedeuten` | 0.55→other, 0.47→other, 0.38→other |
| `jdm. (Dat) etw. (Akk) bringen` | 0.60→const, 0.36→const, 0.61→frame |
| `jdm. (Dat) etw. (Akk) geben` | 0.62→const, 0.36→const, 0.48→const |
| `jdm. (Dat) etw. (Akk) sagen` | 0.43→frame, 0.88→frame, 0.81→frame |
| `jdm. (Dat) etw. (Akk) schreiben` | 0.78→frame, 0.86→frame, 0.50→frame |
| `jdm. (Dat) etw. (Akk) zeigen` | 0.96→frame, 0.41→frame, 0.27→other |
| `jdm. (Dat) gehören` | 0.11→other, 0.20→other, 0.35→other |
| `jdm. (Dat) helfen` | 0.96→frame, 0.57→frame, 0.76→frame |
| `jdm. (Dat) passieren` | 0.67→frame, 0.50→frame, 0.92→frame |
| `jdm. (Dat) stehen` | 0.88→other, 0.53→other, 0.08→other |
| `lange, lang` | 0.85→frame, 0.55→frame, 0.86→frame |
| `mit jdm. / über etw./jdn. sprechen` | 0.53→frame, 0.32→frame, 0.67→frame |
| `nach etw. aussehen` | 0.38→other, 0.42→other, 0.45→other |
| `nichts, nix` | 0.95→frame, 0.59→const, 0.25→frame |
| `selbst, selber` | 0.48→frame, 0.82→frame, 0.38→frame |





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
