"""The two English lines of a card, from a model on your own machine.

A card says four things: the German word, a German sentence using it, that
sentence in English, and what the word means *in that sentence*. The first
two come out of the corpus. The other two exist nowhere -- the study list is
German on both sides, and 59,407 of the 61,409 stored examples have no
translation -- so they are generated.

The meaning is asked for **once per sentence**, not once per word. That is
the whole point of glossing in context: `der Band`, `die Band` and `das Band`
are a volume, a band and a ribbon, and a word that means one thing in the
first example can mean another in the third. A single gloss covering all
three has to hedge -- "history or story" -- which hands the disambiguating
back to the reader, who is the one person who cannot do it yet.

Still one call per word, though. The sentences go together because they are
the same word being used, and a model that sees all three glosses each of
them more consistently than three separate calls would.

Kept in the state database rather than recomputed, because the run is long
and a sentence often teaches more than one word. What is stored is keyed by
the thing itself -- a unit, a sentence -- not by the plan, so rebuilding a
roadmap or aiming at a different list reuses everything already paid for.

The English of a sentence is also asked for **without** a word, by
`translate-sentences`, which walks the whole corpus twenty sentences at a
time. Those land in the same table under `source = 'translate'`, and the
distinction is kept rather than flattened: a card's gloss call is the one that
also asks what the word means, so a sentence the bulk pass has translated has
still never been put to the gloss -- see `missing` and `GlossStore.asked`.
A gloss answer replaces a bulk one, never the other way round.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from corpus.sentence import Sentence
from deck import Card
from state import open_state

# Bumped when the prompt changes in a way that changes the answers. Stored
# beside each row and compared on read, so a wording fix does not leave
# fossils behind. The model is checked alongside it -- see `GlossStore.senses`
# -- because two models answering the same prompt is the same problem wearing
# a different hat.
#
# 2: the gloss became one per sense rather than one per word. Asked once for
#    the word, it had to hedge across the sentences -- "history or story" --
#    which hands the disambiguating back to the one person who cannot do it.
# 3: two worked examples, and `response_format` guiding the decoding. The
#    shape had been described in prose only, and a quarter of the answers
#    came back empty or unparseable: 23 of the first 91 cards. Showing the
#    shape and letting the server enforce it took that to 4%.
# 4: the first worked example grew from two sentences to three. Real cards
#    carry three, and shown only two-sentence examples the model answered
#    three sentences with three senses -- `etwas machen` came back as "to do
#    something", "to perform an action well" and "to carry out an activity",
#    which is one sense worded three ways.
GLOSS_VERSION = 4

# The bulk translation prompt has its own version, so a change to how the
# gloss is asked does not throw away three hundred thousand sentences that
# were never asked that way.
TRANSLATE_VERSION = 1

SCHEMA = """
-- The word's sense *in one sentence*, so the same word can be glossed two
-- ways where it is used two ways. Keyed by both, which is the whole point.
CREATE TABLE IF NOT EXISTS unit_sense (
    kind    TEXT NOT NULL,
    key     TEXT NOT NULL,
    text    TEXT NOT NULL,
    means   TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    model   TEXT NOT NULL DEFAULT '',
    made_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (kind, key, text)
);
-- Superseded by unit_sense before it ever held anything worth keeping: it
-- stored one gloss per word, which had to hedge across the sentences.
DROP TABLE IF EXISTS unit_gloss;
-- Which prompt produced the row: 'gloss', asked beside a word and its
-- sense, or 'translate', asked of the sentence alone. `version` is that
-- prompt's version.
CREATE TABLE IF NOT EXISTS sentence_english (
    text    TEXT PRIMARY KEY,
    english TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    model   TEXT NOT NULL DEFAULT '',
    made_at TEXT NOT NULL DEFAULT '',
    source  TEXT NOT NULL DEFAULT 'gloss'
);
"""

SYSTEM = (
    "You gloss German for an English-speaking learner. "
    "Reply with JSON and nothing else, in this shape:\n"
    '{"english": ["...", ...], '
    '"senses": [{"means": "...", "sentences": [1, 2]}, ...]}\n'
    '"english" is one natural English translation per numbered German '
    "sentence, in the same order.\n"
    '"senses" groups the sentences by what the word MEANS in them. Give one '
    "entry per DISTINCT sense, listing the numbers of the sentences that use "
    "it. Every sentence number must appear in exactly one entry.\n"
    "SPLIT ONLY when a bilingual dictionary would print separate NUMBERED "
    "senses. Reaching for a different English word is NOT a different sense: "
    "maybe/might/perhaps are one sense of vielleicht, and nice/beautiful are "
    "one sense of schön. One entry covering every sentence is the normal "
    "answer and should be your default; two entries need a real difference "
    "in meaning you could point at.\n"
    '"means" is ONE short English sentence of the form "X means Y." where X '
    "is the German word exactly as it was given to you, including its "
    "article.\n"
    # Three sentences, not two, and all three in one sense. Real cards carry
    # three, and shown only two-sentence examples the model began answering
    # three sentences with three senses -- `etwas machen` came back as "to do
    # something", "to perform an action well" and "to carry out an activity",
    # which is one sense worded three ways. The example it needed was the one
    # it had never been shown.
    "\nExample of the usual answer, where the word means one thing "
    "throughout:\n"
    "German word: die Zeit\n"
    "Sentences:\n"
    "1. Ich habe heute leider keine Zeit.\n"
    "2. Die Zeit vergeht viel zu schnell.\n"
    "3. Wir hatten eine schöne Zeit in Berlin.\n"
    '{"english": ["Unfortunately I have no time today.", '
    '"Time passes far too quickly.", '
    '"We had a lovely time in Berlin."], '
    '"senses": [{"means": "die Zeit means time.", "sentences": [1, 2, 3]}]}\n'
    "\nExample of the rarer answer, where it genuinely shifts:\n"
    "German word: die Bank\n"
    "Sentences:\n"
    "1. Wir saßen auf der Bank im Park.\n"
    "2. Ich gehe zur Bank und hole Geld.\n"
    '{"english": ["We sat on the bench in the park.", '
    '"I am going to the bank to get money."], '
    '"senses": [{"means": "die Bank means bench.", "sentences": [1]}, '
    '{"means": "die Bank means the financial institution.", '
    '"sentences": [2]}]}'
)

# The shape, as something the server can enforce rather than something the
# model is asked to remember. Prose alone left a quarter of the answers
# unparseable; guided decoding makes the wrong shape unreachable. The prompt
# keeps its worked examples regardless: the schema fixes the structure, and
# the examples are what make the *content* good -- one sense by default, the
# article kept, the German word quoted back as written.
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "gloss",
        "schema": {
            "type": "object",
            "properties": {
                "english": {"type": "array", "items": {"type": "string"}},
                "senses": {
                    "type": "array",
                    # Deliberately uncapped. Capping it at two was tried
                    # and reverted: `etwas machen` wants three groups, and
                    # forbidding the third made the card fail outright
                    # rather than merge. An over-split card is three nearly
                    # identical blue lines, which is untidy; a failed card
                    # has no gloss at all. The untidy one is the better loss.
                    "items": {
                        "type": "object",
                        "properties": {
                            "means": {"type": "string"},
                            "sentences": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                        },
                        "required": ["means", "sentences"],
                    },
                },
            },
            "required": ["english", "senses"],
        },
    },
}

# The model is asked for JSON and mostly obliges, but wraps it in a fenced
# block often enough to matter over thousands of calls.
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class GlossStore:
    """What the model has already said, keyed by the thing it said it about."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_state(self._path) as conn:
            conn.executescript(SCHEMA)
            self._add_missing_columns(conn)

    @staticmethod
    def _add_missing_columns(conn) -> None:
        """Widen tables made by an earlier version of this file.

        `CREATE TABLE IF NOT EXISTS` is a no-op against a table that already
        exists, columns and all — so a new column has to be added by hand or
        every read of it fails on databases that predate it. Adding rather
        than recreating, because the rows are answers someone paid a model
        for. They default to version 0, which no prompt ever produced, so
        they read as missing and are asked again.
        """
        for table in ("unit_sense", "sentence_english"):
            have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "version" not in have:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN version INTEGER NOT NULL"
                    " DEFAULT 0")
        have = {row[1] for row in conn.execute("PRAGMA table_info(sentence_english)")}
        if "source" not in have:
            # Every row written before the column existed came from the
            # gloss, which was the only thing writing here.
            conn.execute("ALTER TABLE sentence_english ADD COLUMN source"
                         " TEXT NOT NULL DEFAULT 'gloss'")
        conn.commit()

    def senses(self, model: str = "") -> dict[tuple[str, str, str], str]:
        """What each word means in each sentence it was glossed against.

        Only rows the current prompt *and* the current model produced.
        Anything else reads as missing and is asked again.

        The model matters as much as the prompt, which cost a page of bad
        cards to learn: asked for a sentence translation, gemma-4-12B
        returned the word's gloss instead -- "all of" for "Ist das nur in
        Berlin so oder in ganz Deutschland?" -- where Qwen3.5-9B returned the
        sentence. Same prompt, same version, different answers, and no way to
        tell them apart in the table without this.
        """
        with open_state(self._path) as conn:
            return {(kind, key, text): means for kind, key, text, means in
                    conn.execute(
                        "SELECT kind, key, text, means FROM unit_sense"
                        " WHERE version = ? AND (? = '' OR model = ?)",
                        (GLOSS_VERSION, model, model))}

    # A row the current prompts and this model produced. Either prompt will
    # do: a gloss answer and a bulk one are both the English of the sentence,
    # and each is current at its own version.
    _CURRENT = ("(? = '' OR model = ?)"
                " AND ((source = 'gloss' AND version = ?)"
                "   OR (source = 'translate' AND version = ?))")

    @staticmethod
    def _current(model: str) -> tuple:
        return (model, model, GLOSS_VERSION, TRANSLATE_VERSION)

    def sentences(self, model: str = "") -> dict[str, str]:
        """Sentence translations, from a current prompt and this model. See
        `senses` for why the model is part of the question."""
        with open_state(self._path) as conn:
            return dict(conn.execute(
                "SELECT text, english FROM sentence_english"
                f" WHERE {self._CURRENT}", self._current(model)))

    def english_for(self, texts: Iterable[str], model: str = "") -> dict[str, str]:
        """The English of just these sentences, looked up now.

        For a page, which shows a few dozen sentences and is asked for while
        `translate-sentences` is still writing: `sentences` reads the whole
        table, hundreds of thousands of rows by the end, and a copy held
        across requests would miss everything that landed since. Point
        lookups by key cost nothing and are never stale. Rows the model
        declined -- stored empty -- are left out, so a caller can say
        `english.get(text) or fallback` without a second test.
        """
        wanted = list(dict.fromkeys(texts))
        out: dict[str, str] = {}
        with open_state(self._path) as conn:
            # Chunked to stay under SQLite's bound-parameter limit.
            for at in range(0, len(wanted), 500):
                chunk = wanted[at:at + 500]
                marks = ",".join("?" * len(chunk))
                out.update(conn.execute(
                    "SELECT text, english FROM sentence_english"
                    f" WHERE text IN ({marks}) AND english <> ''"
                    f" AND {self._CURRENT}",
                    (*chunk, *self._current(model))))
        return out

    def translated(self, sentences: Iterable[Sentence],
                   model: str = "") -> list[Sentence]:
        """The same sentences, carrying the model's English where it has any.

        The model's answer over what the corpus shipped, as `deck.cards_from`
        already chooses, so a sentence reads the same on a card and on a
        page. Copies: the sentences handed in are usually a cached corpus,
        and the English is a fact about this moment, not about the cache.
        """
        sentences = list(sentences)
        english = self.english_for((s.text for s in sentences), model)
        return [replace(s, translation=english[s.text])
                if s.text in english else s for s in sentences]

    def asked(self, model: str = "") -> set[str]:
        """The sentences that have been put to the *gloss*, whatever it said.

        Not the keys of `sentences`, and the difference is the point: the bulk
        pass translates a sentence without asking what any word means in it,
        so a card whose sentence it has covered is still owed a gloss call.
        This is what `missing` wants for `asked`.
        """
        with open_state(self._path) as conn:
            return {text for (text,) in conn.execute(
                "SELECT text FROM sentence_english"
                " WHERE source = 'gloss' AND version = ?"
                " AND (? = '' OR model = ?)",
                (GLOSS_VERSION, model, model))}

    def save(self, kind: str, key: str,
             rows: Iterable[tuple[str, str, str]], model: str) -> None:
        """One card's worth — (sentence, english, means) per example.

        Written in one transaction so a crash cannot leave a card with its
        translations but not its glosses, which would then be skipped as
        already done.
        """
        now = datetime.now().isoformat(timespec="seconds")
        rows = list(rows)
        with open_state(self._path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO sentence_english"
                " (text, english, version, model, made_at, source)"
                " VALUES (?,?,?,?,?,'gloss')",
                [(text, english, GLOSS_VERSION, model, now)
                 for text, english, _ in rows])
            conn.executemany(
                "INSERT OR REPLACE INTO unit_sense"
                " (kind, key, text, means, version, model, made_at)"
                " VALUES (?,?,?,?,?,?,?)",
                [(kind, key, text, means, GLOSS_VERSION, model, now)
                 for text, _, means in rows if means])
            conn.commit()

    def save_translations(self, english: dict[str, str], model: str) -> None:
        """One batch of the bulk pass -- sentence to English, no word asked.

        Never over a current gloss answer. The two passes may run at once,
        and the gloss saw the sentence beside the word it teaches where this
        saw it alone; the gloss's is the better English for the card, and
        `save` above replaces this unconditionally, so between them the
        gloss wins whichever lands second. Anything else -- an older prompt,
        another model, an earlier bulk answer -- is replaced.
        """
        now = datetime.now().isoformat(timespec="seconds")
        with open_state(self._path) as conn:
            conn.executemany(
                "INSERT INTO sentence_english"
                " (text, english, version, model, made_at, source)"
                " VALUES (?,?,?,?,?,'translate')"
                " ON CONFLICT(text) DO UPDATE SET"
                " english = excluded.english, version = excluded.version,"
                " model = excluded.model, made_at = excluded.made_at,"
                " source = excluded.source"
                " WHERE NOT (source = 'gloss' AND version = ?"
                "            AND model = excluded.model)",
                [(text, said, TRANSLATE_VERSION, model, now, GLOSS_VERSION)
                 for text, said in english.items()])
            conn.commit()


def _parse(reply: str, wanted: int) -> list[tuple[str, str | None]]:
    """The answer as (english, means-or-None) per sentence.

    The model groups the sentences by sense; this flattens the grouping back
    out, so every sentence carries the sense it belongs to. Two sentences
    sharing a sense therefore carry the *same string*, which is what lets a
    renderer collapse them into one line without having to judge whether two
    wordings mean the same thing.
    """
    body = json.loads(_FENCE.sub("", reply).strip())
    english = [str(t).strip() for t in body.get("english", [])]
    # Short is a failure; long is not. A model that returns two translations
    # for three sentences has dropped one, and pairing what is left with the
    # sentences in order would attach English to the wrong German.
    if len(english) < wanted:
        raise ValueError(f"{len(english)} translations for {wanted} sentences")

    means: dict[int, str] = {}
    for sense in body.get("senses", []):
        said = str(sense.get("means", "")).strip()
        if not said:
            raise ValueError("a sense had no meaning")
        for number in sense.get("sentences", []):
            try:
                means[int(number)] = said
            except (TypeError, ValueError):
                raise ValueError(f"sentence number {number!r} is not a number")
    # Partial coverage is allowed, and that is a correction rather than a
    # loosening. The guard used to demand a sense for every sentence and
    # throw the whole answer away otherwise -- translations included -- on
    # 38 cards that failed three passes running. Reading them showed the
    # model was right to refuse: step 16 teaches `jemandem etwas geben`, but
    # two of its three sentences are `es gibt` ("there is") and a
    # subjunctive, which are not that pattern at all. The matcher put them
    # in the deck; the meaning of the pattern is not what they carry. Asked
    # to gloss them as it anyway, the model declined, and discarding its
    # work for being honest is the wrong response.
    #
    # So a sentence with no sense keeps its translation and shows no meaning
    # line, which is also what the renderers already do for a sentence whose
    # sense repeats the one above it.
    return [(english[n - 1], means.get(n)) for n in range(1, wanted + 1)]


def describe(client, card: Card) -> list[tuple[str, str | None]]:
    """Translate a word's sentences and gloss it in each, in a single call."""
    said = [example.text for example in card.examples]
    # The spoken form, not the stored key: the gloss is read by a person, and
    # `jemandem passieren means to happen to someone` is a sentence where
    # `jdm. (Dat) passieren means ...` is a matcher pattern with English
    # bolted on. Asked with the key, the model dutifully quoted it back.
    user = (f"German word: {card.spoken}\n"
            + "Sentences:\n"
            + "\n".join(f"{i}. {text}" for i, text in enumerate(said, 1)))
    return _parse(client.complete(SYSTEM, user, temperature=0.2,
                                  response_format=RESPONSE_FORMAT), len(said))


def missing(cards: Iterable[Card], asked: Iterable[str] = ()) -> list[Card]:
    """The cards still worth asking about.

    A card needs asking when nothing on it has been said at all — no
    English anywhere, or no meaning anywhere. Not when *some* sentence
    lacks one.

    That was asymmetric and the asymmetry bit. Meanings were judged this way
    from the start, because the model legitimately declines to gloss a
    sentence that does not carry the pattern being taught. Translations were
    judged the other way — every sentence had to have one — and a card whose
    third sentence the model would not translate came back on every run for
    ever, failing the same call each time. `das Blatt` and `ausgerechnet`
    did exactly that: two of three sentences glossed, the third refused, and
    the pair queued indefinitely.

    So the test matched `Card.glossed`, which is what the renderers ask — and
    that was right about refusals and wrong about everything else. A rebuild
    changes which sentences teach a step, and a card holding two old sentences
    and one newly promoted one already has English "somewhere", so it was
    never asked again. After one rebuild that left 3,092 shown sentences with
    no translation across 2,341 cards, and a re-run reached seven of them.

    `asked` closes it, and needs nothing new to be stored: `save` already
    writes a row for every sentence it asked about, whether or not the model
    had anything to say. So a sentence absent from that set has never been put
    to the model, while one present with nothing against it has been put and
    declined. The first is worth asking; the second is the case this docstring
    was written about, and is still left alone.

    Pass `GlossStore.asked()` -- the sentences the gloss has seen, not every
    sentence with English against it, because `translate-sentences` writes
    English for the whole corpus without ever asking what a word means. Given
    nothing, this behaves as it did before.
    """
    asked = frozenset(asked or ())
    return [card for card in cards
            if not any(e.translation for e in card.examples)
            or not any(e.means for e in card.examples)
            or any(e.text not in asked for e in card.examples)]


def run(cards: list[Card], store: GlossStore, client, model: str,
        verdicts=None,
        workers: int = 2, on_progress: Callable[[int, int, int], None] | None = None,
        every: int = 25,
        on_card: Callable[[Card, list | None], None] | None = None,
        ) -> tuple[int, int]:
    """Fill in what is missing. Returns (done, failed).

    Generation runs on a pool because the endpoint answers several at once
    for less than several times the wall clock. Two rather than four,
    though, and the reason is worth recording: a llama.cpp-style server cuts
    its context into one slot per parallel request and reserves KV cache for
    each, so asking for more concurrency shrinks the room every request has.
    Against an 11,008-token context, four slots produced a 40-60% failure
    rate -- 500s, 524s and empty bodies -- that looked like an unstable
    server and was in fact this setting. One call needs about 730 tokens all
    told, so the ceiling is the cache rather than the tokens.

    `verdicts`, when given a `SentenceOverrides`, is marked wherever the
    model declines to gloss a sentence. That refusal is the one quality
    signal here that no function can compute: `corpus.quality.score` reads
    length and variety, and `Du hast studiert, also wo die Verlet
    zurückgetreten ist` is an ordinary length with ordinary variety and a
    word that is not German. A model asked to say what it means, and
    declining, has noticed something the characters do not show.

    Writing stays on this thread: SQLite connections do not cross threads
    safely, and the saving is not what takes the time. `on_card` is called
    there too, once per card, with the answer or None -- which is where a
    caller hangs a log or a periodic snapshot without this function needing
    to know what either looks like.
    """
    todo = missing(cards)
    done = failed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, (card, result) in enumerate(
                zip(todo, pool.map(lambda c: _try(client, c), todo)), 1):
            if result is None:
                failed += 1
            else:
                kind = "pattern" if card.is_pattern else "lemma"
                rows = [(example.text, english, means)
                        for example, (english, means)
                        in zip(card.examples, result)]
                store.save(kind, card.word, rows, model)
                if verdicts is not None:
                    for text, _, means in rows:
                        if means is None:
                            verdicts.mark(text, 0.0, source="model")
                done += 1
            if on_card is not None:
                on_card(card, result)
            if on_progress and (index % every == 0 or index == len(todo)):
                on_progress(index, len(todo), failed)
    return done, failed


# A tunnel that gave up on the origin, rather than a model that said
# something wrong. Cloudflare answers 524 when the machine behind it takes
# longer than about a hundred seconds, which is what a busy GPU does -- so
# the cure is to wait, not to ask again immediately into the same queue.
# 500 belongs here despite not sounding like overload: this endpoint returns
# it for long generations, sometimes after ten seconds and sometimes after a
# hundred, and it succeeds on the same card later. Left out, half the
# failures gave up without a single retry.
_OVERLOADED = frozenset({429, 500, 502, 503, 504, 520, 522, 524})


def _try(client, card: Card, attempts: int = 3):
    """One card, retried — patiently for a busy server, briskly for bad JSON.

    Told apart because the right answer differs. Malformed JSON is the
    model's one bad roll and a second ask usually fixes it. A 524 means the
    machine is saturated, and retrying into the same queue spends another
    hundred seconds to be told so again.
    """
    import time                                          # noqa: PLC0415
    import requests                                      # noqa: PLC0415

    wait = 5.0
    for attempt in range(attempts):
        try:
            return describe(client, card)
        except requests.HTTPError as error:
            if error.response is None or \
                    error.response.status_code not in _OVERLOADED:
                return None
            if attempt == attempts - 1:
                return None
            time.sleep(wait)
            wait *= 3
        except requests.RequestException:
            if attempt == attempts - 1:
                return None
            time.sleep(wait)
            wait *= 3
        except (ValueError, KeyError, TypeError):
            # An empty body arrives here too -- `json.loads("")` raises
            # "Expecting value: line 1 column 1", which is not a model that
            # phrased itself badly but a server that answered with nothing.
            # Asking again at once is right for bad JSON and wrong for that,
            # and the two are told apart by whether there was a reply at all.
            if attempt == attempts - 1:
                return None
            time.sleep(wait)
            wait *= 3
    return None
