# Is a cheaper `level` question the same question?

Numbers from `06-level-forms.csv`: 200 subtitle sentences the corpus pass had levelled (question version 1, model jev-1.13.0), stratified by the level it gave, asked again two cheaper ways. A is the same question alone in the request; B is twenty sentences a request with the level descriptions in the state and bare labels as the criteria. Read against the pass's answers.

| form | tokens/sentence | $ per 1,000 | top label agrees | within one level | mean shift (levels) | mean abs. difference (levels) |
|---|---|---|---|---|---|---|
| A | 493 | 0.021 | 79% | 94% | +0.01 | 0.13 |
| B | 157 | 0.007 | 52% | 80% | -0.44 | 0.48 |

The pass's own answers are not gold; they are the same model with more in front of it. Agreement here says whether the cheaper form is *that* question, which is what a video's level averaged from it will inherit.

## Form A: the pass's top label (rows) against the form's (columns)

| pass \ form | A1 | A2 | B1 | B2 | C1 |
|---|---|---|---|---|---|
| A1 | 29 | 10 | 1 | 0 | 0 |
| A2 | 1 | 32 | 6 | 1 | 0 |
| B1 | 0 | 2 | 38 | 0 | 0 |
| B2 | 0 | 2 | 8 | 30 | 0 |
| C1 | 1 | 0 | 7 | 3 | 29 |

## Form B: the pass's top label (rows) against the form's (columns)

| pass \ form | A1 | A2 | B1 | B2 | C1 |
|---|---|---|---|---|---|
| A1 | 33 | 7 | 0 | 0 | 0 |
| A2 | 7 | 33 | 0 | 0 | 0 |
| B1 | 0 | 21 | 18 | 1 | 0 |
| B2 | 1 | 15 | 8 | 16 | 0 |
| C1 | 2 | 4 | 18 | 12 | 4 |

## The sentences the forms move most

**A**:

- pass C1 (2.08) → A1 (0.80) — Die Achse Berlin, Rom, Tokio.
- pass C1 (2.81) → B1 (2.14) — Ich bin im Gefängnis jenseits der fünf Welten.
- pass B2 (2.51) → B1 (1.96) — Der Geist der modernen Welt ist mit dem Jahr 1492 verbunden.
- pass C1 (2.97) → B1 (2.49) — Von bislang 2747 Betrieben auf 22.000 Betriebe, nur in Deutschland.
- pass B2 (2.14) → A2 (1.67) — Genutzt wird AWS vor allem von professionellen Kunden.
- pass A1 (0.64) → A2 (1.06) — Ein Apfel ist, sag ich mal, ein klassisches deutsches Produkt.

**B**:

- pass C1 (2.60) → A1 (0.67) — Die ganze Fülle von ihm.
- pass B2 (2.44) → A1 (0.53) — Die Folge wäre ein Chaos.
- pass C1 (3.65) → B1 (2.04) — Unbesiegt im Feld, verraten in der Heimat.
- pass C1 (2.08) → A1 (0.61) — Die Achse Berlin, Rom, Tokio.
- pass C1 (2.96) → A2 (1.50) — Zu einem Heiligen der Revolution.
- pass B2 (2.75) → A2 (1.31) — Was könnten die Schlimmes anrichten?

