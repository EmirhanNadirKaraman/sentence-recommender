# ---------------------------------------------------------------------------
# VENDORED from language-app/subtitle-scraper/phrase_finder.py
#
# The sentence-to-phrase matcher.  Copied rather than imported so this repo
# stands alone; the only edit is this header.  It reads the verb dictionary
# from ../data/final_result.txt, which is vendored alongside it.
#
# Upstream is the source of truth for changes — re-copy rather than patch here.
# ---------------------------------------------------------------------------
# NB: This module's library functions emit no output. The 13 print() calls
# below all live in main() and report results to stdout when the file is run
# as a script (`python phrase_finder.py`) — stdout IS the product for that
# CLI demo, intentionally left as print rather than logging.

import unicodedata

import spacy
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Load German model
# The medium model, not the small one.  language-app — where this matcher
# comes from — requires it and says so ("Real lemmatisation still requires
# de_core_news_md or larger"); vendoring the code without the model left the
# lemmatiser guessing.  Measured over the failures this project hand-patched,
# `md` gets sixteen of twenty-one right where `sm` did not: `schreien` stays
# `schreien` rather than becoming `schreie`, `gesamt` stays `gesamt` rather
# than `samen`, and `erinnere` reaches `erinnern` so the reflexive pattern
# can match at all.
# `exclude`, not `disable`: the component is never loaded rather than
# loaded and skipped. Nothing here reads `ent_type_` or `doc.ents` any more
# — `get_object_token` used to, and PERSON_NOUNS replaced it — and NER was
# 44% of parse time for eleven decisions in 3,251.
nlp = spacy.load("de_core_news_md", exclude=["ner"])

def load_verb_dictionary(file_path):
    """
    Loads the CSV dictionary where:
    Key: base verb (e.g., 'geben' or 'einladen')
    Value: The full blueprint (e.g., 'geben jdm. etw.')

    When duplicate keys exist, keeps the longer/more detailed value.
    """

    word_map = dict()

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f.readlines():
            # Blank lines and comments, as every other reader of this file
            # already allows — `vocab.goal_list` skips them, and the sibling
            # `study_list.txt` is full of them explaining why an entry was
            # retired. This one split every line on a tab, so the first
            # comment written here took down the parser, and with it every
            # `build-corpus` and `build-roadmap` run.
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            key, _, value = line.partition('\t')
            if not value:
                continue        # no second column: nothing to learn from it
            value = value.strip()  # Remove trailing newlines

            # If key already exists, keep the longer value (more detailed pattern)
            if key in word_map:
                if len(value) > len(word_map[key]):
                    word_map[key] = value
            else:
                word_map[key] = value

    return word_map


_ARTICLES = {'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einen', 'einem', 'einer', 'eines'}

verb_blueprint_map = load_verb_dictionary(_DATA_DIR / "final_result.txt")

# Nouns reach the lookup below lemmatised and lower-cased, while the
# dictionary spells them the way German writes them — `der Hut`, not
# `der hut`.  Without a case-folded view the article retry can never hit,
# and every noun in the corpus falls through to fuzzy matching instead,
# which scores same-noun entries at 1.00 and so picks a gender arbitrarily.
# Restricted to article forms because that is all the retry ever asks for,
# and because folding the whole map would collide `Sie` with `sie`.
_ARTICLE_FORMS = {key.casefold(): key for key in verb_blueprint_map
                  if key.split(" ", 1)[0].lower() in ("der", "die", "das")}

_GENDER_ARTICLE = {"Masc": "der", "Fem": "die", "Neut": "das"}


def article_order(token):
    """der/die/das for a noun, likeliest first.

    Six nouns are listed under two genders and mean different things in
    each — `die Steuer` is a tax and `das Steuer` a helm, `der Leiter` a
    manager and `die Leiter` a ladder.  A fixed order picks the same one
    every time and is therefore wrong about half of them.  The parser has
    already read the gender off the noun and its determiner, so ask it
    first; when it says nothing, fall back to the fixed order, which is all
    the other 1,815 nouns ever need.
    """
    genders = list(token.morph.get("Gender"))
    for child in token.children:
        if child.dep_ == "det":
            genders.extend(child.morph.get("Gender"))
    likely = []
    for gender in genders:
        article = _GENDER_ARTICLE.get(gender)
        if article and article not in likely:
            likely.append(article)
    return likely + [a for a in ("der", "die", "das") if a not in likely]

def generate_trigrams(word):
    """
    Generate trigrams from a word.
    Adds padding at the beginning and end to capture edge trigrams.
    """
    if len(word) < 3:
        return set([word])

    padded_word = f"  {word}  "
    trigrams = set()
    for i in range(len(padded_word) - 2):
        trigrams.add(padded_word[i:i+3])
    return trigrams

def _base_words(dict_word):
    """The word or words a dictionary key should be findable by.

    An entry may name several spellings of one thing — `der Teil, das Teil`,
    `gern, gerne`, `die Universität, die Uni` — and each has to be findable on
    its own.  Indexing the key whole left the comma inside the base word, so
    `Teil` scored 0.62 against `Teil,`, fell under the trustworthiness floor
    and was thrown away: forty-three study-list entries could not be matched
    by anything.  A key without a comma is unchanged, base word and all.
    """
    out = []
    for part in dict_word.split(","):
        words = part.split()
        if not words:
            continue
        out.append(words[1] if len(words) > 1 and words[0].lower() in _ARTICLES
                   else words[0])
    return out or [dict_word]


def _build_trigram_index(dictionary_map):
    """
    Build a trigram inverted index from the dictionary at load time.
    Maps trigram -> list of dict keys whose base word contains that trigram.
    Also pre-computes trigrams for each dict key to avoid regenerating them during lookup.
    Space is O(dict_size * avg_trigrams_per_word) — fixed, never grows with the DB.
    Returns (index, precomputed_trigrams).
    """
    index = {}
    precomputed = {}
    for dict_word in dictionary_map:
        sets = []
        for base_word in _base_words(dict_word):
            tgs = frozenset(generate_trigrams(base_word.lower()))
            sets.append(tgs)
            for tg in tgs:
                if tg not in index:
                    index[tg] = []
                if dict_word not in index[tg]:
                    index[tg].append(dict_word)
        precomputed[dict_word] = tuple(sets)
    return index, precomputed

_trigram_index, _precomputed_trigrams = _build_trigram_index(verb_blueprint_map)

def trigram_similarity(word1, word2):
    """
    Calculate similarity between two words using trigram overlap (Dice coefficient).
    Returns a value between 0 and 1, where 1 is identical.
    """
    trigrams1 = generate_trigrams(word1.lower())
    trigrams2 = generate_trigrams(word2.lower())

    if not trigrams1 or not trigrams2:
        return 0.0

    intersection = len(trigrams1 & trigrams2)
    dice = (2.0 * intersection) / (len(trigrams1) + len(trigrams2))
    return dice

@lru_cache(maxsize=4096)
def find_best_match(target_word, threshold=0.6):
    """
    Find the best matching word from the dictionary using trigram similarity.
    Uses a pre-built inverted index to check only candidate keys that share at
    least one trigram with the target, instead of scanning the full dictionary.
    Results are cached via lru_cache to avoid redundant lookups.
    Returns (best_match, similarity_score) or (None, 0.0) if no match above threshold.
    """
    target_trigrams = generate_trigrams(target_word.lower())

    # Collect only candidates that share at least one trigram
    candidates = set()
    for tg in target_trigrams:
        for dict_word in _trigram_index.get(tg, []):
            candidates.add(dict_word)

    best_match = None
    best_score = 0.0

    for dict_word in candidates:
        # Use pre-computed trigrams instead of regenerating
        # Best of the key's spellings, not a blend of them: `gern, gerne`
        # should be a perfect match for `gern`, and pooling the two would
        # dilute it below one.
        for dict_trigrams in _precomputed_trigrams[dict_word]:
            if not dict_trigrams:
                continue
            intersection = len(target_trigrams & dict_trigrams)
            score = (2.0 * intersection) / (len(target_trigrams) + len(dict_trigrams))

            if score > best_score:
                best_score = score
                best_match = dict_word

    if best_score >= threshold:
        return best_match, best_score
    return None, 0.0

# Nouns that are people, for the object slots. This replaced
# `ent_type_ == "PER"`, which was the only thing in this project reading the
# entity recogniser and cost 44% of parse time to decide 11 of 3,251 object
# tokens — nine of them right and two wrong (`Straße` and `Bescheid` became
# `jdn.`).
#
# Lemmas, lower-cased, because the parser hands back `Herrn` as `Herr`.
# Titles and kinship carry almost all of it; what a list cannot do is
# recognise a surname that is also an ordinary noun, so `Dr. Kraft` is now
# `etw.` where the model had it right. One such against two the model
# invented.
#
# Only words that are people in every reading. `Typ` is left out for meaning
# "kind of thing" as often as "bloke", and group nouns like `Familie` are
# out because the slot is asking about a person, not a set of them.
PERSON_NOUNS = frozenset("""
herr frau dame fräulein doktor professor
mutter vater sohn tochter bruder schwester kind eltern geschwister
oma opa großmutter großvater onkel tante cousin cousine neffe nichte
enkel enkelin ehemann ehefrau gatte gattin mann junge mädchen
mensch person leute kerl baby freund freundin
kollege kollegin nachbar nachbarin gast kunde kundin patient patientin
schüler schülerin student studentin lehrer lehrerin arzt ärztin
chef chefin partner partnerin
""".split())


def get_object_token(child):
    """Maps spaCy dependency labels to jdn./jdm./etw. tokens."""
    # Check if person vs thing
    is_person = (child.pos_ in ["PRON", "PROPN"]
                 or child.lemma_.lower() in PERSON_NOUNS)
    
    # da = dative object, oa = accusative object
    if child.dep_ == "da":
        return "jdm." if is_person else "etw."
    if child.dep_ in ["oa", "obj"]:
        return "jdn." if is_person else "etw."
    return "etw."

def extract_german_logic(doc, overrides=None):
    """
    Extract phrases from a pre-computed spaCy doc.
    Pass a doc (from nlp.pipe or nlp(text)) instead of raw text to avoid redundant NLP.

    `overrides` (#39) is accepted for a uniform extractor signature but NOT applied
    here in slice 1 — no German lemma overrides are seeded yet. German behaviour is
    byte-identical to the pre-#39 call. (German lemma overrides can be wired the same
    way as Spanish if a need shows up.)
    """
    _ = overrides  # reserved; see docstring
    result = []
    consumed = set()

    for token in doc:
        if token.i in consumed:
            continue

        # --- VERB MAPPING LOGIC ---
        if token.pos_ in ["VERB", "AUX"] and token.dep_ != "aux":
            indices = [token.i]
            verb_lemma = token.lemma_.lower()
            
            # Handle Separable Prefixes (e.g., 'ein' in 'einladen')
            prefix = ""
            for child in token.children:
                if child.dep_ == "svp":
                    prefix = child.lemma_.lower()
                    indices.append(child.i)
                    consumed.add(child.i)
            
            full_verb = prefix + verb_lemma if prefix else verb_lemma
            
            # Build the "Live" Blueprint from the sentence
            components = [full_verb]
            for child in token.children:
                # Detect reflexive (sich)
                if child.dep_ == "expl:pv" or (child.lemma_.lower() == "sich"):
                    components.append("sich")
                    indices.append(child.i)
                    consumed.add(child.i)
                
                # Detect Objects (jdn/jdm/etw)
                if child.dep_ in ["oa", "da", "obj"]:
                    components.append(get_object_token(child))
                    indices.append(child.i)
                    consumed.add(child.i)

                    # Also include articles and modifiers of the object
                    for grandchild in child.children:
                        if grandchild.dep_ in ["det", "poss", "amod", "nk"]:
                            indices.append(grandchild.i)
                            consumed.add(grandchild.i)
                
                # Detect Prepositions
                if child.pos_ == "ADP":
                    prep = child.lemma_.lower()
                    indices.append(child.i)
                    consumed.add(child.i)
                    # Find the noun inside the prep phrase
                    obj_in_prep = "etw."
                    for grand in child.children:
                        if grand.dep_ in ["nk", "pobj"]:
                            indices.append(grand.i)
                            consumed.add(grand.i)
                            if grand.pos_ in ["PRON", "PROPN"]:
                                obj_in_prep = "jdm."

                            # Also include articles and modifiers of the prepositional object
                            for great_grand in grand.children:
                                if great_grand.dep_ in ["det", "poss", "amod", "nk"]:
                                    indices.append(great_grand.i)
                                    consumed.add(great_grand.i)
                    components.append(f"{prep} {obj_in_prep}")

            # A verb used reflexively is looked up reflexively first.  The
            # dictionary lists the two separately — `erinnern` is
            # `jdn. (Akk) an etw. erinnern`, the thing you do *to* someone,
            # while `sich erinnern` is `an jdn./etw. sich erinnern` — and
            # asking for the bare lemma answered with the transitive entry
            # every time.  "Sie interessiert sich für Musik" was credited to
            # `jdn. (Akk) interessieren`, and "Ich erinnere mich" matched the
            # transitive form so poorly (0.76) that the analyser threw it
            # away, teaching nothing at all.  `components` already knows,
            # since the constructed blueprint has needed it all along.
            blueprint = None
            match_info = "exact"
            if "sich" in components:
                blueprint = verb_blueprint_map.get(f"sich {full_verb}")
                if blueprint is not None:
                    match_info = "exact (reflexive)"

            if blueprint is None:
                blueprint = verb_blueprint_map.get(full_verb)

            # If not found, try trigram similarity matching
            if blueprint is None:
                best_match, similarity = find_best_match(full_verb)
                if best_match:
                    blueprint = verb_blueprint_map[best_match]
                    match_info = f"fuzzy ({similarity:.2f}): {best_match}"
                else:
                    blueprint = " ".join(components)
                    match_info = "constructed"

            indices.sort()
            result.append({
                "dictionary_entry": blueprint,
                "sentence_phrase": [doc[i].text for i in indices],
                "logic": " -> ".join(components),
                "match_type": match_info,
                "indices": indices
            })

        # --- NOUN/OTHER COLLECTION ---
        elif token.pos_ == "NOUN":
            indices = [token.i]
            noun_lemma = token.lemma_.lower()

            for child in token.children:
                if child.dep_ in ["det", "poss", "amod", "nk"]:
                    indices.append(child.i)
                    consumed.add(child.i)

            # A noun is looked up as a noun first.  The bare lemma is
            # lower-cased, and German lower-cases its nouns straight onto
            # verbs, adjectives and adverbs — `Leben`/`leben`, `Essen`/`essen`,
            # `Weg`/`weg`, `Kosten`/`kosten`, `Arm`/`arm`.  Asking for the bare
            # form first therefore answered with the wrong part of speech and
            # stopped: "Das Essen war gut" matched `etw. (Akk) essen`, the verb
            # *to eat*, and `das Essen` was never emitted by anything.  Eighty
            # of the study list's nouns were unreachable for this reason.
            dictionary_entry = None
            match_info = "exact"
            for article in article_order(token):
                key = _ARTICLE_FORMS.get(f"{article} {noun_lemma}".casefold())
                if key is not None:
                    dictionary_entry = verb_blueprint_map[key]
                    match_info = "exact (with article)"
                    break

            # No article form registered: the bare entry is then the right
            # answer, and for most nouns the only one.
            if dictionary_entry is None:
                dictionary_entry = verb_blueprint_map.get(noun_lemma)

            # If still not found, try trigram similarity matching
            if dictionary_entry is None:
                best_match, similarity = find_best_match(noun_lemma)
                if best_match:
                    dictionary_entry = verb_blueprint_map[best_match]
                    match_info = f"fuzzy ({similarity:.2f}): {best_match}"
                else:
                    dictionary_entry = noun_lemma
                    match_info = "lemma"

            indices.sort()
            result.append({
                "dictionary_entry": dictionary_entry,
                "sentence_phrase": [doc[i].text for i in indices],
                "logic": "NOUN",
                "match_type": match_info,
                "indices": indices
            })

        # --- PRONOUN COLLECTION ---
        elif token.pos_ == "PRON":
            indices = [token.i]
            pronoun_lemma = token.lemma_.lower()

            # Dictionary Lookup with Trigram Matching for Pronouns
            dictionary_entry = verb_blueprint_map.get(pronoun_lemma)
            match_info = "exact"

            if dictionary_entry is None:
                best_match, similarity = find_best_match(pronoun_lemma)
                if best_match:
                    dictionary_entry = verb_blueprint_map[best_match]
                    match_info = f"fuzzy ({similarity:.2f}): {best_match}"
                else:
                    dictionary_entry = pronoun_lemma
                    match_info = "lemma"

            result.append({
                "dictionary_entry": dictionary_entry,
                "sentence_phrase": [doc[i].text for i in indices],
                "logic": "PRON",
                "match_type": match_info,
                "indices": indices
            })

        # --- ADVERB COLLECTION ---
        elif token.pos_ == "ADV":
            indices = [token.i]
            adverb_lemma = token.lemma_.lower()

            # Dictionary Lookup with Trigram Matching for Adverbs
            dictionary_entry = verb_blueprint_map.get(adverb_lemma)
            match_info = "exact"

            if dictionary_entry is None:
                best_match, similarity = find_best_match(adverb_lemma)
                if best_match:
                    dictionary_entry = verb_blueprint_map[best_match]
                    match_info = f"fuzzy ({similarity:.2f}): {best_match}"
                else:
                    dictionary_entry = adverb_lemma
                    match_info = "lemma"

            result.append({
                "dictionary_entry": dictionary_entry,
                "sentence_phrase": [doc[i].text for i in indices],
                "logic": "ADV",
                "match_type": match_info,
                "indices": indices
            })

        # --- ADJECTIVE COLLECTION ---
        elif token.pos_ == "ADJ":
            indices = [token.i]
            adj_lemma = token.lemma_.lower()

            # Dictionary Lookup with Trigram Matching for Adjectives
            dictionary_entry = verb_blueprint_map.get(adj_lemma)
            match_info = "exact"

            if dictionary_entry is None:
                best_match, similarity = find_best_match(adj_lemma)
                if best_match:
                    dictionary_entry = verb_blueprint_map[best_match]
                    match_info = f"fuzzy ({similarity:.2f}): {best_match}"
                else:
                    dictionary_entry = adj_lemma
                    match_info = "lemma"

            result.append({
                "dictionary_entry": dictionary_entry,
                "sentence_phrase": [doc[i].text for i in indices],
                "logic": "ADJ",
                "match_type": match_info,
                "indices": indices
            })

        # --- CATCH-ALL FOR OTHER WORD TYPES ---
        else:
            # Skip punctuation and whitespace
            if token.pos_ in ["PUNCT", "SPACE"]:
                continue

            indices = [token.i]
            word_lemma = token.lemma_.lower()

            # Dictionary Lookup with Trigram Matching
            dictionary_entry = verb_blueprint_map.get(word_lemma)
            match_info = "exact"

            if dictionary_entry is None:
                best_match, similarity = find_best_match(word_lemma)
                if best_match:
                    dictionary_entry = verb_blueprint_map[best_match]
                    match_info = f"fuzzy ({similarity:.2f}): {best_match}"
                else:
                    dictionary_entry = word_lemma
                    match_info = "lemma"

            result.append({
                "dictionary_entry": dictionary_entry,
                "sentence_phrase": [doc[i].text for i in indices],
                "logic": token.pos_,
                "match_type": match_info,
                "indices": indices
            })

    return result


# ---------------------------------------------------------------------------
# Spanish phrase extractor — slice 1 (#36, 2026-05-23) + slice 2 (2026-05-24)
# ---------------------------------------------------------------------------
#
# Conservative, pattern-based Spanish phrase extraction. Three families:
#   1. Finite reflexive verbs          "me lavo"        -> "lavarse"
#   2. Verb + preposition (allowlist)  "dependo de …"   -> "depender de"
#   3. Clitic-attached infinitives     "quiero lavarme" -> "lavarse"  (slice 2)
# Slice 2 also broadened the verb+prep allowlist and the prep-attachment search
# (now matches `mark` deps, e.g. "consiste en practicar").
#
# Reflexive+preposition combos ("acordarse de") are handled via `_ES_REFLEXIVE_PREP`
# for BOTH finite forms (block 1a) and clitic-attached infinitives (block 3a,
# "quiero acordarme de…"). Still deferred (model-bound or needs a new pattern):
# imperatives ("lávate" — es_core_news_sm doesn't tag it as a verb), subjunctive,
# idioms, MWEs.
#
# Output shape is IDENTICAL to extract_german_logic so pipeline.insert_phrases
# consumes it unchanged: each dict carries dictionary_entry / sentence_phrase /
# logic / match_type / indices. Spanish has no blueprint dictionary (that's
# German-only, loaded from final_result.txt), so the canonical form is
# CONSTRUCTED from the sentence — `dictionary_entry` doubles as the
# phrase_blueprint lookup_key and is deduped downstream via ON CONFLICT.

# Reflexive clitic -> (verb Person, allowed verb Numbers | None=any). Requiring
# person/number agreement between the clitic and its finite verb rejects
# non-reflexive object clitics — e.g. "me ve" ("sees me"): ve is 3rd person,
# the clitic "me" is 1st -> no match.
_ES_REFLEXIVE_CLITICS = {
    "me":  ("1", {"Sing"}),
    "te":  ("2", {"Sing"}),
    "se":  ("3", None),
    "nos": ("1", {"Plur"}),
    "os":  ("2", {"Plur"}),
}

# Allowlisted NON-reflexive verb+preposition collocations (verb lemma,
# preposition). Kept conservative on purpose — only emit for a known pair, never
# guess. Reflexive+preposition collocations ("acordarse de", "enamorarse de",
# "convertirse en", "quejarse de") are a DIFFERENT pattern that must yield a
# reflexive canonical ("acordarse de", not "acordar de"); do NOT add those here
# (a finite "me acuerdo de ti" would emit the wrong "acordar de"). They get
# their own set + canonical builder in a later slice (see TODO #36).
_ES_VERB_PREP = {
    # slice 1
    ("depender", "de"), ("pensar", "en"), ("hablar", "de"), ("soñar", "con"),
    ("esperar", "a"), ("tratar", "de"), ("ayudar", "a"), ("aprender", "a"),
    ("empezar", "a"), ("acabar", "de"),
    # slice 2 (each has a test in tests/test_spanish_phrase_extractor.py)
    ("confiar", "en"), ("consistir", "en"), ("creer", "en"),
    ("jugar", "a"), ("salir", "de"), ("llegar", "a"),
}

# Allowlisted REFLEXIVE verb+preposition collocations (bare verb lemma, prep).
# These are deliberately SEPARATE from `_ES_VERB_PREP` above and must NOT be
# merged into it: the canonical is the *reflexive* form ("acordarse de"), built
# as `f"{lemma}se {prep}"`, not "acordar de". They fire only when the finite
# verb also carries an agreeing reflexive clitic (see extract_spanish_logic
# block 1); a matching combo SUPPRESSES the bare reflexive ("acordarse") for
# that token, since the collocation is the real learning unit. (The bare
# reflexive still surfaces from prep-less occurrences elsewhere — phrase_table
# dedups across the corpus.)
_ES_REFLEXIVE_PREP = {
    ("acordar", "de"),    # acordarse de
    ("enamorar", "de"),   # enamorarse de
    ("quejar", "de"),     # quejarse de
    ("preocupar", "por"), # preocuparse por
    ("olvidar", "de"),    # olvidarse de
}


def _es_clitic_agrees(verb, person, numbers):
    """True if finite `verb`'s morphology agrees with a reflexive clitic of the
    given person/number. Permissive when the model didn't tag Person (rare) so
    valid reflexives on under-analysed tokens aren't silently dropped."""
    vp = verb.morph.get("Person")
    if not vp:
        return True
    if person not in vp:
        return False
    if numbers is None:
        return True
    vn = verb.morph.get("Number")
    if not vn:
        return True
    return any(n in numbers for n in vn)


def _es_prep_candidates(verb):
    """Prepositions syntactically attached to `verb`: direct ADP children, plus
    ADP markers heading the verb's oblique/object/clausal complements. The
    grandchild dep is `case` for noun objects ('dependo de mis padres' — 'de'
    cases the obl noun 'padres') and `mark` for infinitive complements
    ('consiste en practicar' — 'en' marks the xcomp verb 'practicar'). Emission
    is still gated by the allowlist, so widening the dep set only finds more
    candidate preps, never invents matches."""
    out = []
    for child in verb.children:
        if child.pos_ == "ADP":
            out.append((child.lemma_.lower(), child.i))
        else:
            for grand in child.children:
                if grand.pos_ == "ADP" and grand.dep_ in ("case", "mark"):
                    out.append((grand.lemma_.lower(), grand.i))
    return out


def _es_deaccent(text):
    """Strip combining accents: 'lavándo' -> 'lavando'. Used only to compare a
    recovered infinitive against an accented surface form."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _es_gerund_base(token, clitic):
    """Recover the infinitive from a gerund carrying an enclitic, or None.

    Why the lemma and not a surface strip: stripping the clitic from
    'lavándose' leaves 'lavándo', which is not an infinitive — unlike the
    infinitive path, where 'lavarme' - 'me' = 'lavar' directly. For gerunds
    es_core_news_sm puts the infinitive in the lemma alongside a pronoun
    ('lavándose' -> 'lavar él'), so the first whitespace-separated piece is the
    form we want.

    That lemma is unreliable, and unreliable in a dangerous way: for
    'preguntándome' the model returns 'preguntándomar', which *ends in -ar* and
    so passes a naive infinitive check while being nonsense. Emitting it would
    put 'preguntándomarse' in phrase_table and teach a word that does not exist.
    Three checks reject it (verified against the live model):

      1. ends in -ar / -er / -ir                      'preguntándomar' passes (!)
      2. shorter than the surface minus its clitic    fails: 14 >= 12
      3. de-accented stem prefixes the surface        fails

    A real gerund is always longer than its infinitive (it adds -ando/-iendo),
    so check 2 alone separates the cases; check 3 guards against a coincidence
    of length. Both are cheap, and a false accept is worse than a miss here.
    """
    lemma_first = (token.lemma_ or "").split()
    if not lemma_first:
        return None
    base = lemma_first[0].lower()
    if not base.endswith(("ar", "er", "ir")) or len(base) <= 2:
        return None

    stem = token.text.lower()[: -len(clitic)]
    if len(base) >= len(stem):
        return None
    if not _es_deaccent(stem).startswith(_es_deaccent(base[:-2])):
        return None
    return base


def extract_spanish_logic(doc, overrides=None):
    """Spanish phrase extractor (finite reflexives + reflexive+preposition combos
    + allowlisted verb+preposition + clitic-attached reflexive infinitives).
    Returns extract_german_logic's dict shape. `doc` must be a Spanish spaCy Doc;
    the caller owns model selection.

    `overrides` (#39) is an optional {observed_lemma: corrected_lemma} map that
    patches spaCy lemmatizer errors (e.g. `duchaber`→`duchar`) before the
    canonical is built. Applied at the single point where the verb lemma is
    read, so both the reflexive (`lemma + "se"`) and verb+prep canonicals use
    the corrected lemma. `None`/empty trusts spaCy."""
    overrides = overrides or {}
    result = []
    # Dedup canonicals within this doc. NB: the pipeline passes one sentence per
    # doc, so this is effectively per-sentence; a multi-sentence doc would dedup
    # across sentences too (acceptable for v1).
    seen = set()

    def _emit(canonical, indices, match_type, logic):
        if canonical in seen:
            return
        seen.add(canonical)
        idx = sorted(set(indices))
        result.append({
            "dictionary_entry": canonical,
            "sentence_phrase": [doc[i].text for i in idx],
            "logic": logic,
            "match_type": match_type,
            "indices": idx,
        })

    for token in doc:
        if token.pos_ != "VERB":
            continue
        verb_lemma = token.lemma_.lower()
        # #39: patch known spaCy lemmatizer errors before building any canonical.
        verb_lemma = overrides.get(verb_lemma, verb_lemma)

        # 1. Reflexive verbs: finite verb + an agreeing reflexive clitic child.
        reflexive_child = None
        for child in token.children:
            if child.pos_ != "PRON":
                continue
            spec = _ES_REFLEXIVE_CLITICS.get(child.text.lower())
            if spec is None:
                continue
            person, numbers = spec
            if _es_clitic_agrees(token, person, numbers):
                reflexive_child = child
                break  # at most one reflexive clitic per finite verb
        if reflexive_child is not None:
            # lemma is the bare infinitive ("lavar"); guard the rare case where
            # the model already returns the reflexive lemma.
            base = verb_lemma if verb_lemma.endswith("se") else f"{verb_lemma}se"
            # 1a. Reflexive + preposition combo ("acordarse de") — the precise
            #     collocation. When it matches, it SUPPRESSES the bare reflexive
            #     for THIS token (bare still surfaces from prep-less occurrences
            #     elsewhere; phrase_table dedups across the corpus).
            combo = False
            for prep_lemma, prep_i in _es_prep_candidates(token):
                if (verb_lemma, prep_lemma) in _ES_REFLEXIVE_PREP:
                    combo = True
                    _emit(f"{base} {prep_lemma}",
                          [token.i, reflexive_child.i, prep_i],
                          "es_reflexive_prep",
                          f"{verb_lemma} + {reflexive_child.text.lower()} + {prep_lemma} (reflexive+prep)")
                    break
            if not combo:
                _emit(base, [token.i, reflexive_child.i], "es_reflexive",
                      f"{verb_lemma} + {reflexive_child.text.lower()} (reflexive)")

        # 2. Verb + preposition from the allowlist.
        for prep_lemma, prep_i in _es_prep_candidates(token):
            if (verb_lemma, prep_lemma) in _ES_VERB_PREP:
                _emit(f"{verb_lemma} {prep_lemma}", [token.i, prep_i],
                      "es_verb_prep", f"{verb_lemma} -> {prep_lemma}")

        # 3. Clitic-attached reflexive infinitive ("quiero lavarme" -> "lavarse"),
        #    plus reflexive+preposition on that infinitive ("quiero acordarme de"
        #    -> "acordarse de", slice 4).
        #    spaCy keeps the enclitic fused into one VERB token (VerbForm=Inf)
        #    whose surface ends in the clitic. Recover the base by stripping that
        #    suffix — the spaCy lemma here is the quirky "lavar yo", so we use the
        #    surface, not the lemma. (The override is applied to the recovered
        #    base; block 1's finite path applies it to the spaCy lemma instead —
        #    two override application points, one per recovery method.)
        verb_form = token.morph.get("VerbForm")
        if "Inf" in verb_form or "Ger" in verb_form:
            surface = token.text.lower()
            # Longest clitic first: 'nos' before 'os', else 'lavarnos' strips to
            # 'lavarn', fails the ends-in-'r' check, and the match is lost.
            for clitic in ("nos", "me", "te", "se", "os"):
                if surface.endswith(clitic):
                    if "Inf" in verb_form:
                        # 'lavarme' - 'me' = 'lavar': the strip yields the
                        # infinitive directly.
                        base = surface[: -len(clitic)]
                        base = base if base.endswith("r") else None
                    else:
                        # Gerund: the strip yields 'lavándo', not an infinitive,
                        # so recover from the lemma under guard. See
                        # _es_gerund_base for why the guard is not optional.
                        base = _es_gerund_base(token, clitic)
                    if base:
                        base = overrides.get(base, base)
                        # Label by the form actually seen, so match_type stays
                        # honest about provenance (a gerund is not an infinitive).
                        form_name = "infinitive" if "Inf" in verb_form else "gerund"
                        bare_type = ("es_reflexive_infinitive" if "Inf" in verb_form
                                     else "es_reflexive_gerund")
                        # 3a. Reflexive + preposition on the infinitive (slice 4)
                        #     — same priority/suppression rule as the finite path
                        #     (block 1a): the combo wins, the bare reflexive is
                        #     skipped for this token. The infinitival "a"
                        #     ("voy a acordarme…") is filtered for free — only
                        #     (base, prep) pairs in _ES_REFLEXIVE_PREP emit.
                        combo = False
                        for prep_lemma, prep_i in _es_prep_candidates(token):
                            if (base, prep_lemma) in _ES_REFLEXIVE_PREP:
                                combo = True
                                _emit(f"{base}se {prep_lemma}",
                                      [token.i, prep_i],
                                      "es_reflexive_prep",
                                      f"{base} + -{clitic} + {prep_lemma} (clitic {form_name} + prep)")
                                break
                        if not combo:
                            _emit(f"{base}se", [token.i], bare_type,
                                  f"{base} + -{clitic} (clitic {form_name})")
                    break

    return result


# ---------------------------------------------------------------------------
# Language-gated dispatcher (Stage 1 of second-language plan, 2026-05-21;
# Spanish first-slice extractor registered 2026-05-23, #36)
# ---------------------------------------------------------------------------
#
# `extract_german_logic` encodes German-specific morphology (separable
# prefixes, Akk/Dat alignment, reflexive sich); `extract_spanish_logic` is a
# narrow first slice for Spanish (reflexives + allowlisted verb+prep). Any
# OTHER language code still returns an empty list — the scraper writes
# word_table + sentence rows as normal but skips phrase rows. Callers don't
# need to special-case.

_LANGUAGE_EXTRACTORS = {
    "de": extract_german_logic,
    "es": extract_spanish_logic,
}


def extract_phrases(doc, language, overrides=None):
    """Dispatch phrase extraction by content language.

    German routes to `extract_german_logic` (byte-identical behaviour
    to the pre-Stage-1 call site); Spanish ('es') routes to
    `extract_spanish_logic` (first slice, #36). Any other language returns
    an empty list so the caller can iterate normally and the scraper writes
    zero phrase rows for it.

    `doc` is a spaCy Doc; we accept it without inspecting language so
    the caller is the source of truth (matches scraper detected_lang,
    matcher request language, chat session language).

    `overrides` (#39) is an optional {observed_lemma: corrected_lemma} map the
    caller loads from the `lemma_override` table (scraper:
    `pipeline.load_lemma_overrides`). It patches spaCy lemmatizer errors before
    canonicals are built. `None`/empty means "trust spaCy" — the pre-#39
    behaviour, so existing call sites are unaffected.
    """
    extractor = _LANGUAGE_EXTRACTORS.get(language)
    if extractor is None:
        return []
    return extractor(doc, overrides)


def get_words_array(text):
    """
    Extract words from text and return as a simple array.
    Returns list of dictionary entries (lemmas).
    """
    doc = nlp(text)
    analysis = extract_german_logic(doc)
    return [item['dictionary_entry'] for item in analysis]

def get_words_detailed_array(text):
    """
    Extract words from text and return as an array with details.
    Returns list of [word, lemma, pos_type, indices] tuples.
    """
    doc = nlp(text)
    analysis = extract_german_logic(doc)
    words_array = []
    for item in analysis:
        word = ' '.join(item['sentence_phrase'])
        lemma = item['dictionary_entry']
        pos = item['logic']
        indices = item['indices']
        words_array.append([word, lemma, pos, indices])
    return words_array


def main():
    # --- TEST ---
    sentence = "Ich lade morgen meine Freunde zum Essen ein"

    # Simple array output
    print("SIMPLE ARRAY:")
    words = get_words_array(sentence)
    print(words)
    print()

    # Detailed array output
    print("DETAILED ARRAY:")
    words_detailed = get_words_detailed_array(sentence)
    for word, lemma, pos, indices in words_detailed:
        print(f"['{word}', '{lemma}', '{pos}', {indices}]")
    print()

    # Full analysis (original)
    print("FULL ANALYSIS:")
    doc = nlp(sentence)
    analysis = extract_german_logic(doc)
    for item in analysis:
        print(f"Phrase:  {' '.join(item['sentence_phrase'])}")
        print(f"Logic:   {item['logic']}")
        print(f"Dict:    {item['dictionary_entry']}")
        print(f"Indices: {item['indices']}")
        if 'match_type' in item:
            print(f"Match:   {item['match_type']}")
        print()


if __name__ == '__main__': 
    main()
