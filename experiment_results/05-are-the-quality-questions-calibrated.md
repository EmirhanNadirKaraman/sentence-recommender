# Are the quality questions calibrated?

Numbers from `05-corpus-pass-slice.csv`: 582 subtitle sentences, one request each carrying every sentence question of the corpus pass (`corpus/questions.py`, version 1). Each group is read against the rule that put it there; a rule is not gold, so this is agreement, and the disagreements are listed to be read.

| group | rule says | n | question | median p | p ≥ 0.5 | p ≥ 0.9 | p ≤ 0.1 |
|---|---|---|---|---|---|---|---|
| no_verb | no finite verb → expect no | 100 | `complete` | 0.68 | 73 | 15 | 1 |
| unbound | unbound pronoun → expect no | 100 | `stands_alone` | 0.59 | 58 | 13 | 0 |
| dialect | dialect → expect no | 104 | `standard` | 0.75 | 85 | 12 | 0 |
| refused | gloss refused → expect mixed | 128 | `well_formed` | 0.82 | 105 | 37 | 2 |
| strange_name | strange name → expect yes | 50 | `well_formed` | 0.82 | 43 | 7 | 0 |
| control | passed every rule → expect yes | 100 | `stands_alone` | 0.80 | 82 | 29 | 0 |
| control | passed every rule → expect yes | 100 | `complete` | 0.96 | 97 | 82 | 0 |
| control | passed every rule → expect yes | 100 | `standard` | 0.91 | 97 | 63 | 0 |
| control | passed every rule → expect yes | 100 | `well_formed` | 0.88 | 95 | 45 | 1 |

591,660 input tokens, 181 s, model jev-1.13.0.

## Disagreements to read

**no_verb** — the rule said no, the judge says yes (p ≥ 0.7):

- 0.97 — Vielen Dank für das aufschlussreiche Hintergrundgespräch.
- 0.96 — Danke schön fürs Zuschauen und bis zum nächsten Mal!
- 0.96 — Danke für die Unterstützung, Tom.
- 0.95 — Also erst einmal herzlichen Glückwunsch zur Schwangerschaft!
- 0.95 — Hey, alles klar bei dir?
- 0.94 — Für mich die Spaghetti Bolognese!
- 0.94 — Alles klar, bis gleich Julian!
- 0.94 — Nein, nur noch 10 Minuten.

**unbound** — the rule said no, the judge says yes (p ≥ 0.7):

- 0.96 — Können Sie die Tür öffnen?
- 0.95 — Wollen Sie ein großes Handy oder ein kleines Handy?
- 0.95 — Er hat ein wenig Schnupfen und Husten.
- 0.94 — Die meisten von uns werden im Krankenhaus sterben.
- 0.93 — Ich gebe Ihnen so viel Geld, wie Sie möchten!
- 0.93 — Gibt es nichts in Ihrem Leben, wofür Sie sterben würden?
- 0.93 — Habt ihr eine Pizza bestellt?
- 0.93 — Es ist immer gut, wenn man neben der gesetzlichen Rente, eine Betriebsrente hat oder private Altersvorsorge möglich ist.

**dialect** — the rule said no, the judge says yes (p ≥ 0.7):

- 0.94 — Sie zerstört unsere wirtschaftliche Leistungsfähigkeit und sie zerstört unsere Kultur.
- 0.94 — Ich schwimme zum Schiff, aber finde keinen Weg hinein.
- 0.93 — Schaut da rein, da gibt's viele weitere spannende Inhalte dazu.
- 0.92 — Du hast dich am Telefon sehr nervös angehört.
- 0.92 — Man hat von hier aus 'ne schöne Sicht auf die Müritz.
- 0.91 — Sie wurden über Jahrzehnte immer wieder vermehrt und retteten so unzählige Leben.
- 0.91 — Was war noch mein Einkommen vor 'nem Jahr?
- 0.91 — Das waren weitaus nicht alle und schon gar keine Frauen.

**refused** — the four the judge rejects most and the four it accepts most:

- 0.08 — Schein nicht so laut, sonst wächst du Mama.
- 0.10 — Die Tiere her sind Freunde des Menschen gebraten.
- 0.11 — Alles k jetzt hängst du auch noch warmes Bier.
- 0.12 — Aber Tommy, was du das Beste ist von allem.
- 0.97 — Ich frage mich, was sich wirklich hinter diesem Angebot verbirgt.
- 0.97 — Ich bin mir nicht sicher, ob ich bestanden habe.
- 0.97 — Ich weiß nicht, wie ich es am besten sagen soll.
- 0.96 — Darüber kann man streiten, aber das Argument geht am Thema vorbei.

**strange_name** — the rule said the sentence is fine, the judge doubts it (p ≤ 0.3):

- 0.16 — Luftkämpfe, wie man sie also äh wie man sie sich vorstellt, Jaachpflieger gegen Jaachflieger waren mit der 163 nicht möglich.
- 0.24 — Kipp mich um und gieße mich über den Krebs aus.

**control** — passed every rule; the judge's lowest on each question:

- `stands_alone` 0.18 — Nämlich dann, wenn irgendeine andere unabhängige Behörde diese Daten geprüft und in ihrem Bericht ausreichend detailliert wiedergibt und veröffentlicht.
- `complete` 0.21 — Die Frauenärztin Michaela Reichert, die ich zu diesem Thema traf.
- `standard` 0.22 — Shopsche Palace heißt das Kackkraft aber den oder bitte sag doch was.
- `well_formed` 0.09 — Die Zeichen verdichten sich, dass heute vormittag nach zem Ringen der beteiligten Kreise der Abschluss einer Regierungskoalition gelungen ist.
- `expression` 0.07 — Im Supermarkt lese ich deutsche Wörter.

## `expression`, unscored

The ten sentences the judge is surest contain a fixed expression, and the ten it is surest do not:

- 0.96 — Und zwar die Hochrechnung des ZDF.
- 0.96 — Und zwar noch nicht einmal mit einem "hab ich gemessen, ist so".
- 0.96 — Und zwar mit Technologien, die eine motivierte, nur etwas weiterentwickelte Menschheit erreichen könnte, wenn sie ins All expandieren will.
- 0.95 — "Tränen lachen" bedeutet: so viel lachen, dass man weinen muss.
- 0.95 — Wir sagen dazu, dass jemand die Schultern hängen lässt.
- 0.94 — Unsere tatarische Umasch, oder so ähnlich, ja. Na ja, sie heißt Rivels.
- 0.92 — Okay. -Bitte sehr. -Cool, Okay.
- 0.92 — Ich wusste, dass es sich lohnt über meinen Schatten zu springen.
- 0.91 — Beispiel für eine Metapher: jemandem das Herz brechen.
- 0.91 — Männer, dann werde ich dir mal auf die Sprünge helfen.

- 0.05 — Er ist ehrenlos und hässlich.
- 0.06 — Wollen Sie ein großes Handy oder ein kleines Handy?
- 0.07 — Wann können wir sie ernten?
- 0.07 — Er war sehr traurig und verzweifelt.
- 0.07 — Im Supermarkt lese ich deutsche Wörter.
- 0.07 — Ich dachte, die Leute hier sind normal.
- 0.08 — Sieben Präpositionen und nur drei mögliche Endungen!
- 0.08 — Einen halben Liter für ein Gewehr.
- 0.08 — Wir entdecken auch die Stadt, verschiedene Museen, sprechen über Kunst.
- 0.08 — Das sind Wörter wie “da”, “wo”, “dort” oder “hier”.
