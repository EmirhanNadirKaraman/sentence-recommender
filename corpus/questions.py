"""The questions the corpus pass asks a judge about a sentence.

Decided one by one on 2026-09-20 (TODO #26): quality first, grammar out.
Each is a typed question in the vendor's own shape — a Noul answers with
the probability of yes, a Choice with one label and its distribution — and
each is defined here once, as data, so the experiment that calibrates a
question and the pass that later asks it over the corpus cannot drift
apart. Question ids are for code and never reach the model, which is why
every instruction says what it is about; state fields are referred to by
backticked paths.

`VERSION` is stored beside every answer. The wording is the question, and
a changed wording is a different question: an answer under version 1 is
not compared with one under version 2, it is asked again.
"""
from __future__ import annotations

VERSION = 1

# What `notation` means to a reader of a canonical, said once.
NOTATION = ("In a canonical, `jdm.`/`jemandem` is a person in the dative and "
            "`jdn.`/`jemanden` a person in the accusative, `etw.`/`etwas` a "
            "thing, `(Dat)`/`(Akk)` its case, `sich` a reflexive; a "
            "preposition written before them belongs to the frame; an article "
            "with a noun is that noun in its ordinary sense; a comma separates "
            "two spellings of one word.")

# --- about the sentence ------------------------------------------------------
# Four questions, each a Noul over `sentence` alone. Together they are what
# "worth showing" has meant in this project, asked instead of approximated.

SENTENCE = {
    # The reader's own wording: it asks the thing rather than listing the
    # ways it fails. Judged alone, so the state carries no line before.
    "stands_alone": {
        "instructions": "Can `sentence` be understood without requiring more context?",
        "criteria": {
            "true": "Understandable alone: `Ich habe es versucht, aber du wolltest es nicht.`",
            "false": "Something in it points outside: `Das steht dir nicht so gut.` — what is `das`?",
        },
    },
    "complete": {
        "instructions": "Is `sentence` one whole utterance — a sentence someone finished saying?",
        "criteria": {
            "true": ("A complete sentence, or a complete short reply: "
                     "`Kein Problem, Mama und Papa!`"),
            "false": ("Cut off, trailing away, or a fragment the subtitler broke in the "
                      "middle: `Um ihn zu feiern, gibt es ein kleines Gewinnspiel, bei dem "
                      "ihr`; two lines glued together; a line that repeats itself."),
        },
    },
    "standard": {
        "instructions": "Is `sentence` ordinary standard German?",
        "criteria": {
            "true": ("Standard German, including casual speech and spoken contractions: "
                     "`hab' ich`, `'nem`, `gibt's`, `ne?`"),
            "false": ("Dialect or a regional form: `Schaun mer mol`, `Grüezi`, `i mog di`, "
                      "a Swiss or Austrian construction a learner of standard German "
                      "would not be taught."),
        },
    },
    # Names and foreign words are taken as given: a name cannot be judged
    # for spelling from one sentence, and `FREE_TAGS` already says a name
    # costs a reader nothing.
    "well_formed": {
        "instructions": ("Is `sentence` correct German as a native speaker would actually "
                         "say or write it?"),
        "criteria": {
            "true": ("Natural German. Casual word order and spoken contractions are fine. "
                     "Names of people, places, brands and titles, numbers, and foreign "
                     "words used the way German uses them (`Inshallah, mein Freund`, `das "
                     "ist cringe`, `Running Mate`) are taken as given and never count "
                     "against it."),
            "false": ("A German word misheard, misspelled or garbled, or words that do not "
                      "fit together: `Ich Schlüssel nicht raus.`, `Aber der Bock hat sich "
                      "gewährt.`, `Ich bin nicht kam mir fehlt nichts.` A sentence that is "
                      "not German at all."),
        },
    },
    # A filter, not a finder: the judge names nothing, so the yes-set goes
    # to the local model for "which one". The only path to `und zwar` and
    # `na ja`, which hang on no pattern unit.
    "expression": {
        "instructions": ("Does `sentence` contain a fixed multiword expression — an idiom, "
                         "a discourse formula, a collocation whose meaning is not the sum "
                         "of its words — that a learner would need to learn as a whole?"),
        "criteria": {
            "true": ("`auf jeden Fall`, `es tut mir leid`, `ums Leben kommen`, `na ja`, "
                     "`und zwar`, `eine Rolle spielen`, `zur Verfügung stehen`."),
            "false": "Every word means what it means on its own, however casual the sentence.",
        },
    },
}

# How hard the sentence is for any learner, as a level learners think in.
# The expected level over the distribution, scaled to 0–1, is the one
# number per sentence; a video's difficulty is the distribution of its
# sentences' levels, computed in code.
LEVEL = {
    "instructions": "At which CEFR level could a learner read `sentence` comfortably?",
    "criteria": {
        "A1": "Short, present tense, everyday words: `Deine Mama ist hier, Lisa.`",
        "A2": ("Simple past or perfect, a modal, one plain clause: `Ich habe vor 5 Jahren "
               "eine Ausbildung gemacht.`"),
        "B1": ("A subordinate clause, common abstract words: `Man weiß gar nicht, was man "
               "machen soll, weil etwas richtig Schlimmes passiert ist.`"),
        "B2": ("Nested clauses, Konjunktiv II or passive, specialised words: `Es ist "
               "sinnlos, jetzt noch darüber nachzudenken, ob die Mannschaft mit einem "
               "anderen Trainer besser gespielt hätte.`"),
        "C1": "Dense, technical or literary German that a fluent reader still slows down for.",
    },
}
LEVELS = ("A1", "A2", "B1", "B2", "C1")

# --- about a unit in the sentence -------------------------------------------
# One of each per pattern unit the analyser found. The unit is given as its
# spoken form and canonical and its token indices, under `units.<id>`.

# B's question: the goal is the word, so what a card must keep off its
# examples is a fixed expression with a meaning of its own, or a different
# word wearing the same letters. Any ordinary sense or frame of the word,
# an auxiliary or a modal included, is a fair example of the word.
PLAIN = {
    "instructions": ("Are the tokens of `units.{id}` the word `units.{id}.spoken` itself, "
                     "in any of its ordinary senses or frames?"),
    "criteria": {
        "true": ("The word used as itself — any sense, any preposition or case it takes "
                 "here, reflexive or not, as an auxiliary or a modal too. `stehen` meaning "
                 "stand, be written, or have a position are all `stehen`."),
        "false": ("Part of a fixed expression with a meaning of its own — `ums Leben "
                  "kommen` is not `das Leben`, `Bescheid wissen` is not `wissen` — or a "
                  "different word that looks the same: `gehört` from `hören` is not "
                  "`gehören`, `gelassen` the adjective is not `lassen`."),
    },
}

# The sentence teaches the word: a reader who had every other word could
# work this one out, which is the premise of an i+1 step. A rubric, not a
# yes/no: asked as a Noul it came back compressed — yes rows at a median of
# .68, no rows at .60, nothing outside .2–.9 — and the three levels spread
# it to .74 against .55, with 88% of the yes rows above the no median. The
# expected level over the distribution, scaled to 0–1, is the number. It
# ranks a card's examples beside `plain`; it never gates.
GUESSABLE = {
    "instructions": ("How much does `sentence` tell a learner who knows every other "
                     "word about what `units.{id}.spoken` means?"),
    "criteria": [
        ("Nothing: the word could mean almost anything here. `Ich weiß nicht.` for "
         "`wissen`; `Das tun wir.` for `tun`."),
        ("A hint: the sentence narrows it to a few possibilities. `Er hat ein wenig "
         "Schnupfen und Husten.` for `der Husten` — something you have when ill."),
        ("Gives it away: a learner could say what the word means from this sentence "
         "alone. `Ich brauche unbedingt eine gute Note.` for `brauchen`; `Schwer "
         "bewaffnet nehmen sie dort 11 Sportler als Geiseln.` for `nehmen`."),
    ],
}


def state_for(text: str, tokens: list[str], units: dict[str, dict]) -> dict:
    """The state one request carries: the sentence, its tokens, its units.

    `units` maps an id to `{"spoken", "canonical", "tokens"}`; the ids are
    what the per-unit questions name in their instructions.
    """
    return {"sentence": text, "tokens": tokens, "units": units, "notation": NOTATION}


def questions_for(units: dict[str, dict], level: bool = True) -> dict:
    """Every question for one sentence, as the vendor's question objects."""
    from typesafe_sdk import Choice, Noul, Score          # noqa: PLC0415 — optional client

    asked: dict = {key: Noul(instructions=q["instructions"], criteria=q["criteria"])
                   for key, q in SENTENCE.items()}
    if level:
        asked["level"] = Choice(instructions=LEVEL["instructions"], criteria=LEVEL["criteria"])
    for unit_id in units:
        asked[f"plain:{unit_id}"] = Noul(
            instructions=PLAIN["instructions"].format(id=unit_id), criteria=PLAIN["criteria"])
        asked[f"guessable:{unit_id}"] = Score(
            instructions=GUESSABLE["instructions"].format(id=unit_id),
            criteria=GUESSABLE["criteria"])
    return asked
