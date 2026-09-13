"""Experiment 3 — would Stanza lemmatise better than spaCy?

The corpus is analysed by `de_core_news_md` plus a repair layer that grew one
failure at a time: `data/lemma_overrides.txt`, `data/lemma_fixes.txt`, the
lookup-table fallback, the invented-lemma guard and the corpus-majority vote
(see `corpus/analyzer.py`). Stanza's German models are trained on the UD
treebanks with a dictionary-first lemmatiser, so the question is whether they
get right, natively, what this project patches by hand — and what they get
wrong that spaCy does not.

Stanza is measured directly rather than through `spacy-stanza`. The wrapper
adds nothing to the lemmas — they are Stanza's either way — and it would add
two things that muddy a comparison: its own tokeniser, which expands `zum`
into `zu dem` so token streams stop being one-to-one, and UD dependency labels
where the matcher expects TIGER's (`oa`, `da`, `nk`, `svp`). The lemma
question can be answered without either. Stanza is run over spaCy's own
tokens (`tokenize_pretokenized`), which is also the only integration that
leaves the matcher untouched; one run with Stanza's own tokeniser measures
how much that choice costs.

Two evaluation sets, because the obvious one is rigged:

  targeted   the project's own correction files — every one a case spaCy
             failed on. Stanza scoring well here is necessary, not
             sufficient: it says nothing about where Stanza fails instead.
  sample     random teachable sentences, no ground truth. Both models are
             held to the same objective yardsticks, and their disagreements
             are written out for adjudication in both directions.

Objective yardsticks, chosen to hit the failures that motivated the repair
layer: how often a lemma is a word at all, how often a finite verb comes back
unreduced, whether a surface gets the same lemma at the start of a sentence
as in the middle, and whether the noun/verb homographs keep their capital.

`run` does the slow part once and writes everything per token; `analyse`
reads that back and is cheap, so the numbers can be re-cut without a second
hour of Stanza. One Stanza pipeline is resident at a time and each finishes
into its own file, because the first attempt held three and was killed for
memory beside a roadmap build — a re-run picks up where it stopped.
Standalone on purpose: `run_all.py` does not import this, because it would
then require torch.

    python experiments/lemmatisers.py run --sample 8000
    python experiments/lemmatisers.py workers      # throughput under worker processes
    python experiments/lemmatisers.py analyse
"""
from __future__ import annotations

import argparse
import csv
import difflib
import gc
import gzip
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Settings                                   # noqa: E402
from corpus.analyzer import (INFINITIVE_ENDINGS, VERB_TAGS,   # noqa: E402
                             UnitAnalyzer, _LEMMA_FIXES, _OVERRIDES)
from db import Database                                       # noqa: E402
from db.word_repo import FREE_TAGS, PUNCTUATION_TAGS          # noqa: E402
from experiments import results                               # noqa: E402

NAME = "03-lemmatisers"
SENTENCES = results.RESULTS / f"{NAME}-sentences.csv.gz"
TOKENS = results.RESULTS / f"{NAME}-tokens.csv.gz"
CASES = results.RESULTS / f"{NAME}-cases.csv"
TARGETED = results.RESULTS / f"{NAME}-targeted.csv"
FORMS = results.RESULTS / f"{NAME}-forms.txt.gz"
TIMINGS = results.RESULTS / f"{NAME}-timings.csv"
WORKERS = results.RESULTS / f"{NAME}-workers.csv"
DISAGREEMENTS = results.RESULTS / f"{NAME}-disagreements.csv"
CANDIDATES = results.RESULTS / f"{NAME}-candidates.csv"
TO_JUDGE = results.RESULTS / f"{NAME}-to-judge.csv"
JUDGED = results.RESULTS / f"{NAME}-judged.csv"
REPORT = results.RESULTS / "03-would-stanza-lemmatise-better.md"


def _part(config: str) -> Path:
    """One lemmatiser's answers, written the moment it finishes."""
    return results.RESULTS / f"{NAME}-part-{config}.csv.gz"


SPACY_MODEL = "de_core_news_md"
# Every lemma source that is compared. `md` is the model's own output,
# `md_repaired` what the analyser makes of it; the three Stanza columns are
# the default package over spaCy's tokens, the same over its own tokens, and
# the `default_accurate` package (transformer tagger, charlm lemmatiser).
CONFIGS = ("md", "md_repaired", "st", "own", "acc")
STANZA = {"st": ("default", True), "acc": ("default_accurate", True),
          "own": ("default", False)}

WORD = re.compile(r"[^\W\d_]+")
# The tags that become vocabulary: nouns, verbs, adjectives, adverbs. The
# rest are function words, which sit in the known set from the start and
# whose lemma is a matter of convention — UD says `ich` for `mir`, spaCy
# says `mir` — rather than of getting a word right.
OPEN_CLASS = ("N", "V", "ADJ", "ADV")
FINITE = ("FIN", "IMP")
SEED = 0.42
CHUNK = 500


# --- run -----------------------------------------------------------------

def run(sample: int, transcript_share: float) -> None:
    import spacy                                   # noqa: PLC0415 — heavy
    import stanza                                  # noqa: PLC0415 — heavy

    settings = Settings()
    analyzer = UnitAnalyzer(frozenset())
    nlp = spacy.load(SPACY_MODEL, exclude=["ner"])
    versions = {"spacy": spacy.__version__, "spacy_model": nlp.meta["version"],
                "stanza": stanza.__version__}
    print(f"spacy {versions['spacy']} / {SPACY_MODEL} {versions['spacy_model']}"
          f" / stanza {versions['stanza']}", flush=True)

    n_transcript = round(sample * transcript_share)
    sentences = _sample(settings, sample - n_transcript, n_transcript)
    print(f"sample: {len(sentences)} sentences "
          f"({sample - n_transcript} subtitle, {n_transcript} transcript)", flush=True)
    texts = [text for _, _, text in sentences]
    if not FORMS.exists():
        _write_forms(settings)
    _write_sentences(sentences)
    cases = _cases(settings, nlp)

    timings = {r["config"]: float(r["seconds"]) for r in _read(TIMINGS)} \
        if TIMINGS.exists() else {}
    t = time.time()
    docs = list(nlp.pipe(texts, batch_size=CHUNK))
    timings["md"] = time.time() - t
    print(f"  spacy: {len(docs)} sentences in {timings['md']:.1f}s", flush=True)
    _write_timings(timings, len(texts), versions)

    # Whitespace tokens are not words and Stanza's pretokenised input cannot
    # carry them, so they are dropped here and everywhere below.
    kept = [[i for i, tok in enumerate(doc) if not tok.is_space] for doc in docs]
    words = [[doc[i].text for i in keep] for doc, keep in zip(docs, kept)]
    _write_part("md", [
        [(doc[i].text, doc[i].lemma_, doc[i].tag_, doc[i].pos_) for i in keep]
        for doc, keep in zip(docs, kept)], [])
    _write_part("md_repaired", [
        [(doc[i].text, analyzer._verb_lemma(doc[i]), doc[i].tag_, doc[i].pos_)
         for i in keep] for doc, keep in zip(docs, kept)], [])
    case_docs = list(nlp.pipe([c["sentence"] for c in cases]))
    _write_part("md", None, [
        (n, _case_answer(doc, case, lambda tok: tok.lemma_))
        for n, (doc, case) in enumerate(zip(case_docs, cases))])
    _write_part("md_repaired", None, [
        (n, _case_answer(doc, case, analyzer._verb_lemma))
        for n, (doc, case) in enumerate(zip(case_docs, cases))])
    case_words = [[tok.text for tok in doc if not tok.is_space] for doc in case_docs]
    del docs
    gc.collect()

    for config, (package, pretokenized) in STANZA.items():
        if _part(config).exists():
            print(f"  stanza {config}: already done, skipping", flush=True)
            continue
        pipe = _stanza(stanza, package, pretokenized)
        inputs = words if pretokenized else [t.replace("\n", " ") for t in texts]
        rows, timings[config] = _run_stanza(pipe, inputs, config)
        answers = []
        if pretokenized:
            for n, (case, cw) in enumerate(zip(cases, case_words)):
                target = int(case["target"])
                if target >= 0:
                    out = pipe([cw]).sentences[0].words[target]
                    answers.append((n, (out.text, out.lemma or "", out.xpos or "",
                                        out.upos or "")))
        _write_part(config, rows, answers)
        _write_timings(timings, len(texts), versions)
        del pipe, rows
        gc.collect()

    _merge(kept, cases)
    print("run complete", flush=True)


def _sample(settings, n_subtitle: int, n_transcript: int):
    """Random teachable sentences, the same ones on every run."""
    out = []
    with Database(settings.own) as db:
        db.rows("SELECT setseed(%s)", (SEED,))
        for build, n in (("subtitle", n_subtitle), ("transcript", n_transcript)):
            if n:
                out.extend(
                    (build, sid, text) for sid, text in db.rows(
                        "SELECT id, text FROM corpus_sentence WHERE build = %s"
                        " AND teachable ORDER BY random() LIMIT %s", (build, n)))
    return out


def _stanza(stanza, package: str, pretokenized: bool):
    processors = "tokenize,pos,lemma" if pretokenized else "tokenize,mwt,pos,lemma"
    return stanza.Pipeline(
        "de", package=package, processors=processors,
        tokenize_pretokenized=pretokenized, tokenize_no_ssplit=not pretokenized,
        use_gpu=False, download_method=None, logging_level="ERROR")


def _run_stanza(pipe, inputs: list, label: str):
    """Sentences in chunks, so a slow run says where it is.

    Only the four strings per word are kept; a Stanza `Document` for five
    hundred sentences is far larger than the answers in it.
    """
    out: list[list[tuple]] = []
    started = time.time()
    for start in range(0, len(inputs), CHUNK):
        chunk = inputs[start:start + CHUNK]
        doc = pipe(chunk) if isinstance(chunk[0], list) else pipe("\n\n".join(chunk))
        if len(doc.sentences) != len(chunk):
            raise RuntimeError(f"{label}: {len(chunk)} sentences in, "
                               f"{len(doc.sentences)} out")
        for sentence in doc.sentences:
            out.append([(tok.text, "+".join(w.lemma or "" for w in tok.words),
                         "+".join(w.xpos or "" for w in tok.words),
                         "+".join(w.upos or "" for w in tok.words))
                        for tok in sentence.tokens])
        del doc
        print(f"  stanza {label}: {len(out)}/{len(inputs)} sentences, "
              f"{time.time() - started:.0f}s", flush=True)
    return out, time.time() - started


def _write_forms(settings) -> None:
    """Every word the corpus has ever written, for the attestation test.

    Kept beside the tokens rather than recomputed, so `analyse` needs no
    database and the rule deciding what counts as a word can change without
    another hour of Stanza.
    """
    forms: set[str] = set()
    with Database(settings.own) as db:
        with db.cursor() as cur:
            cur.execute("SELECT text FROM corpus_sentence")
            for (text,) in cur:
                forms.update(w.casefold() for w in WORD.findall(text))
    with gzip.open(FORMS, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(sorted(forms)))
    print(f"  forms: {len(forms)} surface forms in the corpus", flush=True)


def _write_sentences(sentences) -> None:
    with gzip.open(SENTENCES, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sent", "build", "id", "text"])
        for n, (build, sid, text) in enumerate(sentences):
            writer.writerow([n, build, sid, text])


def _write_part(config: str, rows, answers) -> None:
    """`rows`: per sentence, per token `(text, lemma, xpos, upos)`; `answers`:
    the same for the targeted cases, keyed by case number. Either may be
    added later — spaCy's cases arrive after its sample, Stanza's together."""
    path = _part(config)
    existing = list(_read_gz(path)) if path.exists() else []
    with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["kind", "sent", "k", "text", "lemma", "xpos", "upos"])
        for r in existing:
            if (r["kind"] == "sample") == (rows is None):
                writer.writerow([r["kind"], r["sent"], r["k"], r["text"],
                                 r["lemma"], r["xpos"], r["upos"]])
        for n, sentence in enumerate(rows or []):
            for k, (text, lemma, xpos, upos) in enumerate(sentence):
                writer.writerow(["sample", n, k, text, lemma, xpos, upos])
        for n, answer in answers:
            if answer is not None:
                writer.writerow(["case", n, 0, *answer])


def _write_timings(timings, sentences: int, versions) -> None:
    with TIMINGS.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["config", "sentences", "seconds", "sentences_per_second",
                         "spacy", "spacy_model", "stanza"])
        for config, seconds in timings.items():
            writer.writerow([config, sentences, round(seconds, 1),
                             round(sentences / seconds, 1), versions["spacy"],
                             versions["spacy_model"], versions["stanza"]])


def _merge(kept, cases) -> None:
    """The per-lemmatiser parts, joined into one row per spaCy token."""
    parts = {config: defaultdict(dict) for config in CONFIGS}
    answers = {config: {} for config in CONFIGS}
    for config in CONFIGS:
        for r in _read_gz(_part(config)):
            if r["kind"] == "sample":
                parts[config][int(r["sent"])][int(r["k"])] = r
            else:
                answers[config][int(r["sent"])] = r
    fields = ["sent", "i", "surface", "initial", "tag", "pos",
              "md", "md_repaired", "st", "st_xpos", "st_upos", "own", "acc",
              "acc_xpos"]
    with gzip.open(TOKENS, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for n, keep in enumerate(kept):
            md, rep = parts["md"][n], parts["md_repaired"][n]
            st, acc = parts["st"][n], parts["acc"][n]
            own = _align([md[k]["text"] for k in range(len(keep))],
                         [parts["own"][n][k] for k in sorted(parts["own"][n])])
            initial = next((k for k in range(len(keep))
                            if md[k]["xpos"] not in PUNCTUATION_TAGS
                            and md[k]["upos"] != "PUNCT"), -1)
            for k, i in enumerate(keep):
                writer.writerow({
                    "sent": n, "i": i, "surface": md[k]["text"],
                    "initial": int(k == initial), "tag": md[k]["xpos"],
                    "pos": md[k]["upos"], "md": md[k]["lemma"],
                    "md_repaired": rep[k]["lemma"], "st": st[k]["lemma"],
                    "st_xpos": st[k]["xpos"], "st_upos": st[k]["upos"],
                    "own": own.get(k, ""), "acc": acc[k]["lemma"],
                    "acc_xpos": acc[k]["xpos"],
                })
    rows = []
    for n, case in enumerate(cases):
        row = {"set": case["set"], "sentence": case["sentence"],
               "position": case["position"], "surface": case["surface"],
               "gold": case["gold"], "tag": "", "found": int(int(case["target"]) >= 0)}
        for config in ("md", "md_repaired", "st", "acc"):
            answer = answers[config].get(n)
            row[config] = answer["lemma"] if answer else ""
            row[f"ok_{config}"] = int(row[config].lower() == case["gold"]) if answer else ""
            if config == "md" and answer:
                row["tag"] = answer["xpos"]
                row["surface"] = answer["text"]
        rows.append(row)
    _write_csv(TARGETED, rows)
    print(f"  merged: {sum(len(k) for k in kept)} tokens, {len(rows)} targeted rows",
          flush=True)


def _align(ours: list[str], theirs: list[dict]) -> dict[int, str]:
    """Stanza's own tokens matched to spaCy's, position by position.

    A multiword token (`zum` -> `zu dem`) keeps its surface and joins its
    lemmas with `+`; whatever the two tokenisers split differently is simply
    absent, and the share absent is one of the results.
    """
    matcher = difflib.SequenceMatcher(None, ours, [t["text"] for t in theirs],
                                      autojunk=False)
    out: dict[int, str] = {}
    for a, b, size in matcher.get_matching_blocks():
        for offset in range(size):
            out[a + offset] = theirs[b + offset]["lemma"]
    return out


# --- throughput under workers ----------------------------------------------

def workers(sample: int) -> None:
    """Stanza across worker processes, the way `build-corpus` runs spaCy.

    The single-process figure in `run` is not the one a rebuild pays. spaCy
    gets 1.67x from four workers here (TODO item 1); whether Stanza does is
    a separate question, because torch already spreads one process over
    several cores. Each worker loads its own pipeline — macOS spawns rather
    than forks — and the start-up is reported apart from the steady rate,
    since a full rebuild amortises it and a small one does not.
    """
    from concurrent.futures import ProcessPoolExecutor   # noqa: PLC0415
    import spacy                                          # noqa: PLC0415

    settings = Settings()
    with Database(settings.own) as db:
        db.rows("SELECT setseed(%s)", (SEED,))
        texts = db.column("SELECT text FROM corpus_sentence WHERE build = 'subtitle'"
                          " AND teachable ORDER BY random() LIMIT %s", (sample,))
    nlp = spacy.load(SPACY_MODEL, exclude=["ner"])
    words = [[tok.text for tok in doc if not tok.is_space]
             for doc in nlp.pipe(texts, batch_size=CHUNK)]
    rows = []
    for n in (1, 2, 4):
        shares = [words[i::n] for i in range(n)]
        started = time.time()
        with ProcessPoolExecutor(max_workers=n) as pool:
            done = list(pool.map(_stanza_worker, shares))
        wall = time.time() - started
        load = max(d[0] for d in done)
        work = max(d[1] for d in done)
        rows.append({"workers": n, "sentences": sample, "wall_seconds": round(wall, 1),
                     "slowest_load_seconds": round(load, 1),
                     "slowest_parse_seconds": round(work, 1),
                     "sentences_per_second_steady": round(sample / work, 1),
                     "sentences_per_second_wall": round(sample / wall, 1)})
        print(f"  stanza x{n}: {sample} sentences, wall {wall:.1f}s, slowest worker "
              f"loaded in {load:.1f}s and parsed in {work:.1f}s "
              f"({sample / work:.0f} sentences/s steady)", flush=True)
    _write_csv(WORKERS, rows)


def _stanza_worker(words):
    import stanza                                          # noqa: PLC0415
    started = time.time()
    pipe = _stanza(stanza, "default", pretokenized=True)
    loaded = time.time()
    pipe(words)
    return loaded - started, time.time() - loaded


# --- the targeted set ------------------------------------------------------

# The two documented failures, and the mid-sentence control for the first.
README_CASES = [
    ("Hast du Zeit?", "Hast", "haben"),
    ("Du hast Zeit.", "hast", "haben"),
    ("Gibst du das Tom?", "Gibst", "geben"),
    ("Willst du das?", "Willst", "wollen"),
]


def _cases(settings, nlp) -> list[dict]:
    """The project's correction files as test cases, chosen once and kept.

    Each is one token in one sentence with a hand-checked answer. The
    sentences come from the corpus itself, so the register is the one that
    matters; where a form is also found sentence-initially that occurrence
    is included, because that position is where spaCy is weakest. `target`
    is the token's index among spaCy's non-space tokens, or -1 when the
    sentence turned out not to hold the form as a token after all.
    """
    if CASES.exists():
        return _read(CASES)
    cases: list[dict] = []
    with Database(settings.own) as db:
        db.rows("SELECT setseed(%s)", (SEED,))
        for surface, gold in _pairs(_OVERRIDES).items():
            for position, text in _holding(db, surface):
                cases.append({"set": "overrides", "sentence": text, "position": position,
                              "surface": surface, "gold": gold, "observed": ""})
        for observed, gold in _pairs(_LEMMA_FIXES).items():
            for position, text in _inventing(db, nlp, observed, gold):
                cases.append({"set": "fixes", "sentence": text, "position": position,
                              "surface": "", "gold": gold, "observed": observed})
    for word, gold in _goal_words().items():
        cases.append({"set": "goals", "sentence": word, "position": "bare",
                      "surface": word, "gold": gold, "observed": ""})
    for text, surface, gold in README_CASES:
        cases.append({"set": "readme", "sentence": text,
                      "position": "initial" if text.startswith(surface) else "mid",
                      "surface": surface, "gold": gold, "observed": ""})
    for case, doc in zip(cases, nlp.pipe([c["sentence"] for c in cases])):
        case["target"] = _target(doc, case)
    _write_csv(CASES, cases)
    print(f"  cases: {len(cases)} targeted cases", flush=True)
    return cases


def _target(doc, case: dict) -> int:
    k = 0
    for token in doc:
        if token.is_space:
            continue
        if case["surface"] and token.text.lower() == case["surface"].lower():
            return k
        if case["observed"] and token.lemma_.lower() == case["observed"]:
            return k
        k += 1
    return -1


def _case_answer(doc, case: dict, lemma_of):
    target = int(case["target"])
    if target < 0:
        return None
    token = [tok for tok in doc if not tok.is_space][target]
    return (token.text, lemma_of(token), token.tag_, token.pos_)


def _pairs(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].split()
            if len(line) == 2:
                out[line[0]] = line[1].lower()
    return out


def _goal_words() -> dict[str, str]:
    """Single-word goal entries: the bare-word path, no context at all."""
    out: dict[str, str] = {}
    path = _OVERRIDES.parent / "goal_lemmas.txt"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if "\t" in line:
            entry, gold = line.split("\t", 1)
            if " " not in entry.strip():
                out[entry.strip()] = gold.strip().lower()
    return out


def _holding(db, surface: str, mid: int = 3):
    r"""Corpus sentences containing `surface` as a word, one of them initial.

    Postgres does the narrowing and Python the deciding: under this
    database's collation `\M` sees a word end before an umlaut, so `geh\M`
    matches `gehört`. Over-fetch, then keep what a Unicode-aware boundary
    accepts.
    """
    whole = re.compile(rf"(?<![^\W\d_]){re.escape(surface)}(?![^\W\d_])", re.I)
    initial = re.compile(rf"^\W*{re.escape(surface)}(?![^\W\d_])", re.I)
    found = []
    for text in db.column(
            "SELECT text FROM corpus_sentence WHERE teachable AND text ~* %s"
            " ORDER BY random() LIMIT 4", (rf"^\W*{re.escape(surface)}\M",)):
        if initial.search(text):
            found.append(("initial", text))
            break
    for text in db.column(
            "SELECT text FROM corpus_sentence WHERE teachable AND text ~* %s"
            " ORDER BY random() LIMIT %s",
            (rf"\S.*\m{re.escape(surface)}\M", mid * 3)):
        if whole.search(text) and not initial.search(text):
            found.append(("mid", text))
            if len(found) > mid:
                break
    return found


def _inventing(db, nlp, observed: str, gold: str, want: int = 3):
    """Sentences where spaCy produces the invented lemma `observed`.

    Found by looking for the corrected word and keeping the sentences where
    the model still invents — the correction is keyed on the model's output,
    so that is the only way to know a sentence exhibits the failure.
    """
    texts = db.column(
        "SELECT text FROM corpus_sentence WHERE teachable AND text ~* %s"
        " ORDER BY random() LIMIT 30", (rf"\m{re.escape(gold[:5])}",))
    out = []
    for text, doc in zip(texts, nlp.pipe(texts)):
        if any(t.lemma_.lower() == observed for t in doc):
            out.append(("mid", text))
            if len(out) == want:
                break
    return out


# --- analyse ---------------------------------------------------------------

def analyse() -> None:
    sentences = {int(r["sent"]): r for r in _read_gz(SENTENCES)}
    tokens = list(_read_gz(TOKENS))
    timings = {r["config"]: r for r in _read(TIMINGS)}
    targeted = _read(TARGETED)
    judged = _read(JUDGED) if JUDGED.exists() else []
    noun_splits = analyzer_noun_splits()

    attested = _attester()
    ambiguous = _normalise(tokens)
    for t in tokens:
        for config in CONFIGS:
            t[f"att_{config}"] = "1" if t[config] and attested(t[config]) else "0"
    content = [t for t in tokens if _is_content(t)]
    summary: dict = {
        "spacy": timings["md"]["spacy"], "spacy_model": timings["md"]["spacy_model"],
        "stanza": timings["md"]["stanza"],
        "sentences": len(sentences), "tokens": len(tokens),
        "content_tokens": len(content),
    }
    for config in CONFIGS:
        if config in timings:
            summary[f"sps_{config}"] = timings[config]["sentences_per_second"]
    for r in (_read(WORKERS) if WORKERS.exists() else []):
        summary[f"sps_st_x{r['workers']}"] = r["sentences_per_second_steady"]

    # 1. Is the lemma a word at all?
    for config in CONFIGS:
        have = [t for t in content if t[config]]
        summary[f"nonword_{config}"] = _share(
            sum(1 for t in have if t[f"att_{config}"] == "0"), len(have))

    # 2. Finite verbs handed back unreduced, each model judged by its own tags.
    for config in CONFIGS:
        tag = _tag_column(config)
        verbs = [t for t in content
                 if t[config] and t[tag].startswith(VERB_TAGS)
                 and t[tag].endswith(FINITE)]
        summary[f"identity_verb_{config}"] = _share(
            sum(1 for t in verbs if _identity(t["surface"], t[config])), len(verbs))
        summary[f"finite_verbs_{config}"] = len(verbs)

    # 3. The same surface at the start of a sentence and in the middle.
    inconsistent: dict[str, list] = {}
    for config in CONFIGS:
        surfaces, agree, bad = _position_consistency(content, config)
        summary[f"position_surfaces_{config}"] = surfaces
        summary[f"position_consistent_{config}"] = _share(agree, surfaces)
        inconsistent[config] = bad

    # 4. Noun/verb homographs: does the noun keep its capital?
    for config in CONFIGS:
        nouns = [t for t in content if t["surface"] in noun_splits
                 and t["tag"] == "NN" and t[config]]
        summary[f"homograph_nouns_{config}"] = len(nouns)
        summary[f"homograph_capital_{config}"] = _share(
            sum(1 for t in nouns if t[config][:1].isupper()), len(nouns))

    # 5. Names: the tagger's appetite for calling a sentence-initial word one.
    for label, tag in (("md", "tag"), ("st", "st_xpos"), ("acc", "acc_xpos")):
        initial = [t for t in tokens if t["initial"] == "1"]
        mid = [t for t in tokens if t["initial"] == "0" and t["tag"] not in
               PUNCTUATION_TAGS and t["pos"] != "PUNCT"]
        summary[f"name_initial_{label}"] = _share(
            sum(1 for t in initial if t[tag] == "NE"), len(initial))
        summary[f"name_mid_{label}"] = _share(
            sum(1 for t in mid if t[tag] == "NE"), len(mid))

    # 5b. Two habits of Stanza's dictionary worth a number each: a lemma
    # offered as `denken|gedenken`, and pre-1996 spelling (`Abschluß`).
    for config in ("st", "own", "acc"):
        summary[f"ambiguous_{config}"] = _share(ambiguous[config], len(content))
        summary[f"old_spelling_{config}"] = _share(
            sum(1 for t in content if "ß" in t[config]
                and "ß" not in t["surface"].lower()), len(content))
    words = [t for t in tokens if t["tag"] not in PUNCTUATION_TAGS
             and t["pos"] != "PUNCT"]
    for label, tag in (("md", "tag"), ("st", "st_xpos"), ("acc", "acc_xpos")):
        summary[f"ne_{label}"] = _share(
            sum(1 for t in words if t[tag] == "NE"), len(words))
    summary["ne_md_only"] = sum(1 for t in words if t["tag"] == "NE"
                                and t["st_xpos"] != "NE")
    summary["ne_st_only"] = sum(1 for t in words if t["tag"] != "NE"
                                and t["st_xpos"] == "NE")

    # 6. Where the analyser and Stanza part ways.
    disagreements = [t for t in content if t["st"]
                     and t["md_repaired"].lower() != t["st"].lower()]
    summary["disagree_tokens"] = len(disagreements)
    summary["disagree_share"] = _share(len(disagreements), len(content))
    open_class = [t for t in content if t["tag"].startswith(OPEN_CLASS)]
    open_disagreements = [t for t in disagreements if t["tag"].startswith(OPEN_CLASS)]
    summary["open_class_tokens"] = len(open_class)
    summary["open_disagree_tokens"] = len(open_disagreements)
    summary["open_disagree_share"] = _share(len(open_disagreements), len(open_class))
    summary["open_disagree_sentences"] = _share(
        len({t["sent"] for t in open_disagreements}), len(sentences))
    builds = Counter(r["build"] for r in sentences.values())
    summary["subtitle_sentences"] = builds.get("subtitle", 0)
    summary["transcript_sentences"] = builds.get("transcript", 0)
    by_sentence: dict[str, tuple[set, set]] = defaultdict(lambda: (set(), set()))
    for t in content:
        by_sentence[t["sent"]][0].add(t["md_repaired"].lower())
        by_sentence[t["sent"]][1].add(t["st"].lower())
    differing = sum(1 for a, b in by_sentence.values() if a != b)
    summary["disagree_sentences"] = _share(differing, len(by_sentence))
    summary["acc_agrees_with_st"] = _share(
        sum(1 for t in content if t["acc"].lower() == t["st"].lower()),
        len(content))
    for config in CONFIGS:
        summary[f"distinct_{config}"] = len({t[config].lower() for t in content
                                             if t[config]})

    # 7. What pretokenising costs Stanza.
    aligned = [t for t in content if t["own"]]
    summary["own_aligned"] = _share(len(aligned), len(content))
    summary["own_agrees_with_st"] = _share(
        sum(1 for t in aligned if t["own"].lower() == t["st"].lower()),
        len(aligned))

    # 8. The targeted set.
    for kind in ("overrides", "fixes", "goals", "readme"):
        rows = [r for r in targeted if r["set"] == kind and r["found"] == "1"]
        summary[f"{kind}_rows"] = len(rows)
        for config in ("md", "md_repaired", "st", "acc"):
            summary[f"{kind}_ok_{config}"] = sum(
                1 for r in rows if r[f"ok_{config}"] == "1")

    # 9. What Stanza would add to the correction files, used as an oracle.
    candidates = _candidates(content)
    summary["candidate_overrides"] = sum(1 for c in candidates if c["kind"] == "override")
    summary["candidate_fixes"] = sum(1 for c in candidates if c["kind"] == "fix")

    # 10. Adjudication, when someone has done it.
    verdicts = Counter(r["verdict"] for r in judged)
    summary["judged"] = len(judged)
    for verdict in ("st", "md", "both", "neither"):
        summary[f"judged_{verdict}"] = verdicts.get(verdict, 0)
    # The adjudicated shares, scaled back to the whole sample: what part of
    # the open-class tokens, and of the sentences, Stanza moves from wrong
    # to right net of what it breaks. An estimate — the sample of 200 is
    # random, but a share of 200 carries a few points of noise.
    if judged:
        net = (verdicts.get("st", 0) - verdicts.get("md", 0)) / len(judged)
        summary["net_open_tokens_gained"] = round(
            net * float(summary["open_disagree_share"]), 4)
        summary["net_sentences_gained"] = round(
            net * float(summary["open_disagree_sentences"]), 4)

    _write_disagreements(disagreements, sentences)
    _write_candidates(candidates)
    _write_to_judge(open_disagreements, sentences)
    history = results.append(NAME, summary)
    _report(history, summary, inconsistent, targeted, candidates, judged, sentences)


def analyzer_noun_splits() -> frozenset[str]:
    return UnitAnalyzer(frozenset()).noun_splits


def _normalise(tokens) -> Counter:
    """Stanza's `a|b` lemmas: take the first, count how often it happened."""
    ambiguous: Counter = Counter()
    for t in tokens:
        for config in ("st", "own", "acc"):
            if "|" in t[config]:
                ambiguous[config] += 1
                t[config] = t[config].split("|", 1)[0]
    return ambiguous


def _attester():
    """Is this string a German word anyone has written?

    The test `data/lemma_fixes.txt` was built with: a lemma is plausible if
    the corpus writes it somewhere, or the lookup table knows it as a form
    or as a lemma. Compounds defeat any fixed list, and a corpus that says
    `Vermittlungsversuche` once has never written the singular a lemmatiser
    correctly produces — so a word nobody has written still passes when it
    splits into a known head and a known modifier, with or without a
    linking -s/-n/-en. `raketenba` and `teilche` split into nothing.
    """
    with gzip.open(FORMS, "rt", encoding="utf-8") as handle:
        forms = set(handle.read().split())
    lookup = UnitAnalyzer(frozenset()).verb_lemmas
    cache: dict[str, bool] = {}

    def known(word: str) -> bool:
        return word in forms or lookup.is_lemma(word) or bool(lookup.get(word))

    def compound(word: str) -> bool:
        for i in range(3, len(word) - 3):
            if not lookup.is_lemma(word[i:]):
                continue
            modifier = word[:i]
            for link in ("", "s", "n", "en", "e", "er", "es"):
                stem = modifier[:len(modifier) - len(link)] if link else modifier
                if modifier.endswith(link) and len(stem) >= 3 and known(stem):
                    return True
        return False

    def attested(lemma: str) -> bool:
        word = lemma.casefold()
        if word not in cache:
            if "|" in word or "+" in word:
                cache[word] = all(attested(p) for p in re.split(r"[|+]", word) if p)
            elif "-" in word:
                cache[word] = known(word) or attested(word.rsplit("-", 1)[1])
            else:
                cache[word] = known(word) or compound(word)
        return cache[word]
    return attested


def _read_gz(path: Path):
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _is_content(t: dict) -> bool:
    return (t["tag"] not in PUNCTUATION_TAGS and t["tag"] not in FREE_TAGS
            and t["pos"] != "PUNCT" and bool(t["md"]) and t["md"] != "--")


def _tag_column(config: str) -> str:
    return {"st": "st_xpos", "own": "st_xpos", "acc": "acc_xpos"}.get(config, "tag")


def _identity(surface: str, lemma: str) -> bool:
    low = surface.lower()
    return lemma.lower() == low and not low.endswith(INFINITIVE_ENDINGS)


def _share(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _position_consistency(content, config):
    """Surfaces seen at least twice in each position: same majority lemma?"""
    initial: dict[str, Counter] = defaultdict(Counter)
    mid: dict[str, Counter] = defaultdict(Counter)
    for t in content:
        if not t[config]:
            continue
        where = initial if t["initial"] == "1" else mid
        where[t["surface"].lower()][t[config].lower()] += 1
    surfaces = agree = 0
    bad = []
    for surface, first in initial.items():
        rest = mid.get(surface)
        if not rest or sum(first.values()) < 2 or sum(rest.values()) < 2:
            continue
        surfaces += 1
        a, b = first.most_common(1)[0][0], rest.most_common(1)[0][0]
        if a == b:
            agree += 1
        else:
            bad.append((surface, a, b, sum(first.values()), sum(rest.values())))
    bad.sort(key=lambda x: -(x[3] + x[4]))
    return surfaces, agree, bad


def _candidates(content) -> list[dict]:
    """Lines Stanza would add to the correction files, with their evidence.

    An override candidate is a verb the analyser still hands back unreduced
    where Stanza gives an attested infinitive; a fix candidate is a lemma the
    analyser produced that nobody has ever written, beside one Stanza gave
    that somebody has.
    """
    overrides: Counter = Counter()
    fixes: Counter = Counter()
    examples: dict[tuple, str] = {}
    for t in content:
        st = t["st"].lower()
        if not st:
            continue
        repaired = t["md_repaired"].lower()
        surface = t["surface"].lower()
        if (t["tag"].startswith(VERB_TAGS) and _identity(t["surface"], repaired)
                and st != surface and st.endswith(INFINITIVE_ENDINGS)
                and t["att_st"] == "1"):
            overrides[(surface, st)] += 1
            examples.setdefault(("override", surface, st), t["sent"])
        elif (t["att_md_repaired"] == "0" and t["att_st"] == "1"
              and st != repaired and st != surface):
            fixes[(repaired, st)] += 1
            examples.setdefault(("fix", repaired, st), t["sent"])
    out = []
    for (wrong, right), n in overrides.most_common():
        out.append({"kind": "override", "from": wrong, "to": right, "count": n,
                    "sent": examples[("override", wrong, right)]})
    for (wrong, right), n in fixes.most_common():
        out.append({"kind": "fix", "from": wrong, "to": right, "count": n,
                    "sent": examples[("fix", wrong, right)]})
    return out


def _write_disagreements(disagreements, sentences) -> None:
    rows = [{"sent": t["sent"], "build": sentences[int(t["sent"])]["build"],
             "surface": t["surface"], "initial": t["initial"], "tag": t["tag"],
             "st_xpos": t["st_xpos"], "md": t["md"], "md_repaired": t["md_repaired"],
             "st": t["st"], "acc": t["acc"], "att_md_repaired": t["att_md_repaired"],
             "att_st": t["att_st"], "text": sentences[int(t["sent"])]["text"]}
            for t in disagreements]
    _write_csv(DISAGREEMENTS, rows)


def _write_candidates(candidates) -> None:
    _write_csv(CANDIDATES, candidates)


def _write_to_judge(disagreements, sentences, n: int = 200) -> None:
    """A fixed sample of open-class disagreements for a reader to adjudicate.

    Written only once — `03-lemmatisers-judged.csv` is that file with a
    `verdict` column filled in by hand, and overwriting the sample would
    orphan the verdicts.
    """
    if TO_JUDGE.exists() or JUDGED.exists():
        return
    import random                                   # noqa: PLC0415
    picked = random.Random(42).sample(disagreements, min(n, len(disagreements)))
    rows = [{"n": k, "surface": t["surface"], "tag": t["tag"],
             "md_repaired": t["md_repaired"], "st": t["st"], "acc": t["acc"],
             "text": sentences[int(t["sent"])]["text"], "verdict": "", "note": ""}
            for k, t in enumerate(picked, 1)]
    _write_csv(TO_JUDGE, rows)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


# --- the report --------------------------------------------------------------

def _report(history, s, inconsistent, targeted, candidates, judged, sentences) -> None:
    def pct(key: str) -> str:
        return f"{float(s[key]):.1%}"

    def table(rows: list[list[str]], head: list[str]) -> str:
        out = "| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n"
        for row in rows:
            out += "| " + " | ".join(str(c) for c in row) + " |\n"
        return out

    labels = {"md": "spaCy md, raw", "md_repaired": "spaCy md + repair layer",
              "st": "Stanza default, spaCy tokens", "own": "Stanza default, own tokens",
              "acc": "Stanza accurate, spaCy tokens"}
    yard = table([[labels[c], pct(f"nonword_{c}"), pct(f"identity_verb_{c}"),
                   f"{pct(f'position_consistent_{c}')} of {s[f'position_surfaces_{c}']}",
                   f"{pct(f'homograph_capital_{c}')} of {s[f'homograph_nouns_{c}']}",
                   s[f"distinct_{c}"]] for c in CONFIGS],
                 ["lemma source", "not a word", "finite verb unreduced",
                  "same lemma initial/mid", "homograph noun keeps capital",
                  "distinct lemmas"])
    speed = table([[labels[c], s.get(f"sps_{c}", "")] for c in ("md", "st", "own", "acc")],
                  ["pipeline", "sentences / s (one process)"])
    names = table([[lab, pct(f"name_initial_{k}"), pct(f"name_mid_{k}")]
                   for k, lab in (("md", "spaCy md"), ("st", "Stanza default"),
                                  ("acc", "Stanza accurate"))],
                  ["tagger", "initial word tagged NE", "mid-sentence word tagged NE"])
    targ = table([[kind, s[f"{kind}_rows"]] +
                  [f"{s[f'{kind}_ok_{c}']} ({s[f'{kind}_ok_{c}'] / max(s[f'{kind}_rows'], 1):.0%})"
                   for c in ("md", "md_repaired", "st", "acc")]
                  for kind in ("overrides", "fixes", "goals", "readme")],
                 ["set", "rows", "spaCy raw", "spaCy + repair", "Stanza default",
                  "Stanza accurate"])
    incon = ""
    for config in ("md_repaired", "st"):
        rows = inconsistent[config][:8]
        if rows:
            incon += f"\n{labels[config]}:\n\n" + table(
                [[w, a, b, f"{n1}+{n2}"] for w, a, b, n1, n2 in rows],
                ["surface", "lemma when initial", "lemma mid-sentence", "seen"])
    misses = [r for r in targeted if r["found"] == "1" and r["ok_st"] == "0"
              and r["set"] in ("overrides", "goals", "readme")][:12]
    miss_table = table([[r["set"], r["surface"], r["gold"], r["st"], r["acc"],
                         r["md_repaired"], r["sentence"][:60]] for r in misses],
                       ["set", "form", "should be", "Stanza", "Stanza acc.",
                        "spaCy + repair", "sentence"])
    cand = table([[c["kind"], c["from"], c["to"], c["count"],
                   sentences[int(c["sent"])]["text"][:60]] for c in candidates[:15]],
                 ["kind", "analyser says", "Stanza says", "times", "example"])
    verdict = _verdict(s, judged)
    judged_section = _judged_section(s, judged, table)

    body = f"""\
# Would Stanza lemmatise better than spaCy?

Numbers from `03-lemmatisers.csv`, one row per run. Per-token working in
`03-lemmatisers-tokens.csv.gz`; every disagreement with its sentence in
`03-lemmatisers-disagreements.csv`; the correction files replayed in
`03-lemmatisers-targeted.csv`. Rows are comparable only within a
`spacy_model`/`stanza` version pair.

## What this tests

The corpus is lemmatised by `{SPACY_MODEL}` plus a repair layer that grew
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

{speed}
Stanza's models are LSTMs; on this machine Metal (MPS) is seven times slower
than the CPU, so these are CPU figures, one process each. **Taken on a loaded
machine** — a `build-roadmap` ran throughout — so, as `TODO.md` warns of every
timing here, trust the ratios before the absolutes: a quiet probe beforehand
gave spaCy 423 and Stanza 76 sentences/s, the same 5–6× apart.

A rebuild does not run one process. `build-corpus` gives spaCy four workers,
which the README measures at about 700 sentences/s over the Tatoeba build.
Stanza under workers, steady state after each has loaded its models:

{_workers_table(table)}
Torch already spreads one Stanza process over several cores, so a second
process adds a fifth and a fourth adds nothing — the ceiling on this machine
is about {float(s.get('sps_st_x2', s.get('sps_st', 0))):.0f} sentences/s however the work is
split (thread-per-worker tuning untested). Against the corpus's {314929:,}
teachable sentences that is about {314929 / max(float(s.get('sps_st_x2', s.get('sps_st', 1))), 1) / 60:.0f} minutes for a full rebuild, to
spaCy's {314929 / 700 / 60:.0f}.

## The yardsticks

{len(sentences):,} random teachable sentences ({s['subtitle_sentences']:,} subtitle,
{s['transcript_sentences']:,} transcript), {s['content_tokens']:,} content tokens
(spaCy's view of which tokens are content: not punctuation, not a name,
number or foreign word). No ground truth; each column is an objective test.

*Not a word*: the lemma is written nowhere in the corpus and is neither a
form nor a lemma in spaCy's 355k-entry German table — the test
`data/lemma_fixes.txt` was built with. *Finite verb unreduced*: a token the
model itself tags as a finite or imperative verb, whose lemma is its own
surface and does not end in -en/-n. *Same lemma initial/mid*: surfaces seen
at least twice at the start of a sentence and twice elsewhere, counted
consistent when the majority lemma agrees — the `Hast du Zeit?` failure.
*Homograph*: the {len(analyzer_noun_splits())} nouns in `data/noun_verb_splits.txt`, tagged NN, whose
lemma kept its capital.

{yard}
{names}
Stanza offers two lemmas joined by `|` (`denken|gedenken`, an HDT habit)
for {pct('ambiguous_st')} of content tokens — the first is taken above — and a
pre-1996 spelling (`Abschluß`, `Tip`) for {pct('old_spelling_st')}. The taggers call
{pct('ne_md')} (spaCy) and {pct('ne_st')} (Stanza) of word tokens a name: {s['ne_md_only']}
tokens are a name to spaCy alone and {s['ne_st_only']} to Stanza alone.

The two disagree on **{pct('disagree_share')}** of content tokens, which touches
**{pct('disagree_sentences')}** of sentences' lemma sets — but most of that is
function words, where the lemma is a convention (UD says `ich` for `mir`
and keeps `im` whole; spaCy says `mir` and `in`) and the word is in the
known set regardless. On the open classes — nouns, verbs, adjectives,
adverbs, the tokens that become vocabulary — they disagree on
**{pct('open_disagree_share')}** ({s['open_disagree_tokens']:,} of {s['open_class_tokens']:,}). Stanza's accurate package agrees
with its default on {pct('acc_agrees_with_st')} of content tokens. Given its own tokeniser,
Stanza aligns with spaCy's tokens on {pct('own_aligned')} of content tokens and gives the
same lemma on {pct('own_agrees_with_st')} of those — pretokenising costs it little.

Where the same surface gets different lemmas by position (most frequent first):
{incon}
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

{targ}
What Stanza still gets wrong on this set:

{miss_table}
## Stanza as an oracle for the correction files

Whichever way the runtime question goes, Stanza's answers can be mined
offline. A candidate override is a verb the analyser still hands back
unreduced where Stanza gives an attested infinitive; a candidate fix is a
lemma nobody has written beside one somebody has. {s['candidate_overrides']} override
lines and {s['candidate_fixes']} fix lines in this sample alone, all in
`03-lemmatisers-candidates.csv`. Every one needs reading before it goes in a
file: the same test would have proposed `sein -> mein`.

{cand}
{judged_section}
## What it means

{verdict}

## History

{_history_table(history)}
"""
    REPORT.write_text(body, encoding="utf-8")
    print(f"  wrote experiment_results/{REPORT.name}")


def _workers_table(table) -> str:
    if not WORKERS.exists():
        return "(not measured — run `workers`)\n"
    rows = _read(WORKERS)
    return table([[r["workers"], r["sentences_per_second_steady"],
                   r["slowest_load_seconds"], r["sentences_per_second_wall"]]
                  for r in rows],
                 ["Stanza workers", "sentences / s, steady", "start-up (s)",
                  "sentences / s incl. start-up"])


def _judged_section(s, judged, table) -> str:
    if not judged:
        return ("## Adjudication\n\nNot yet done. `03-lemmatisers-to-judge.csv` holds "
                "200 random open-class disagreements; copy it to "
                "`03-lemmatisers-judged.csv`, fill `verdict` with `st`, `md`, `both` "
                "or `neither` and `kind` with why, and re-run `analyse`.\n")
    n = int(s["judged"])
    rows = [[v, s[f"judged_{v}"], f"{int(s[f'judged_{v}']) / n:.0%}"]
            for v in ("st", "md", "both", "neither")]
    judges = ", ".join(sorted({r.get("judge", "") for r in judged} - {""})) or "unrecorded"
    kinds = ""
    for verdict, title in (("st", "Stanza was right because spaCy + repair"),
                           ("md", "spaCy + repair was right because Stanza"),
                           ("both", "Both defensible")):
        tally = Counter(r.get("kind", "") for r in judged if r["verdict"] == verdict)
        examples = defaultdict(list)
        for r in judged:
            if r["verdict"] == verdict and len(examples[r.get("kind", "")]) < 3:
                right, wrong = ((r["st"], r["md_repaired"]) if verdict == "st"
                                else (r["md_repaired"], r["st"]))
                examples[r.get("kind", "")].append(
                    f"{r['surface']} → {right} (not {wrong})"
                    if verdict != "both" else f"{r['md_repaired']} / {r['st']}")
        kinds += f"\n{title}:\n\n" + table(
            [[k, c, "; ".join(examples[k])] for k, c in tally.most_common()],
            ["kind", "rows", "examples"])
    return (f"## Adjudication\n\n{n} random disagreements on open-class tokens, read by "
            f"hand (judge: {judges}). `st` means Stanza was right, `md` the analyser, "
            "`both` that either reading is defensible — mostly a convention the two "
            "treebanks differ on — and `neither` that both were wrong. Every row, with "
            "its sentence and the reason, is in `03-lemmatisers-judged.csv`.\n\n"
            + table(rows, ["verdict", "count", "share"]) + kinds)


def _verdict(s, judged) -> str:
    slow = float(s.get("sps_md", 1)) / max(float(s.get("sps_st", 1)), 0.01)
    minutes_st = 314929 / float(s.get("sps_st", 1)) / 60
    minutes_md = 314929 / float(s.get("sps_md", 1)) / 60
    lines = [
        f"**Yes, measurably, on the words that matter — but not as a pipeline "
        f"swap.** A finite verb comes back unreduced "
        f"{float(s['identity_verb_st']):.1%} of the time under Stanza against "
        f"{float(s['identity_verb_md_repaired']):.1%} after the repair layer, and "
        f"{float(s['identity_verb_md']):.1%} before it: the failure the whole two-pass "
        f"design exists for, `Hast du Zeit?`, is one Stanza's dictionary rarely makes. "
        f"The noun/verb homographs keep their capital {float(s['homograph_capital_st']):.0%} of "
        f"the time against {float(s['homograph_capital_md_repaired']):.0%}. Non-word "
        f"lemmas come out level ({float(s['nonword_st']):.1%} against "
        f"{float(s['nonword_md_repaired']):.1%}), but for different reasons, as the "
        f"adjudication shows.",
    ]
    if judged:
        n = int(s["judged"]); st, md = int(s["judged_st"]), int(s["judged_md"])
        both, neither = int(s["judged_both"]), int(s["judged_neither"])
        lines.append(
            f"Read by hand, Stanza was right in {st} of {n} open-class disagreements and "
            f"the analyser in {md}; {both} were conventions and {neither} were wrong both "
            f"ways. Scaled back to the sample, that is a net "
            f"{float(s['net_open_tokens_gained']):.1%} of open-class tokens moved from "
            f"wrong to right (give or take 0.4 points: it rests on 200 verdicts), in "
            f"roughly {float(s['net_sentences_gained']):.0%} of "
            f"sentences — and a wrong lemma in a sentence is a phantom unknown that "
            f"keeps it out of the roadmap. The shape of the two error sets is the "
            f"larger finding. Stanza wins the "
            f"long tail — plurals, participles, clipped and second-person verbs left "
            f"unreduced, compounds truncated to non-words — which is exactly what "
            f"`lemma_overrides.txt` and `lemma_fixes.txt` chase one line at a time, and "
            f"the sample turned up new inventions (`pfannkuch` beside the listed "
            f"`pfannkuche`, `willen`, `traumus`) that the files do not yet hold. spaCy "
            f"wins a short list of *systematic* Stanza habits: pre-1996 spellings, an "
            f"inheritance of 1990s newspaper training text (`Abschluß`, `Rußland`, "
            f"`Tip`), particles read as verbs "
            f"or nouns (`danke` → `Dank`, `bitte` → `bitten`, `ne` → `ein`), the spoken "
            f"`'s` contraction (`geht's` → `gehe'en`), `weißt` → `weißen`, and the "
            f"capitalised clipped imperative that opens so much spoken German (`Sag`, "
            f"`Hör`, `Mach`, `Geh`; `Lass` → `laß`). Each of those is a rule or a "
            f"twenty-line table — the imperatives are already in "
            f"`lemma_overrides.txt`, which is surface-keyed and would go on applying — "
            f"and the long tail is not.")
    ceiling = float(s.get("sps_st_x2", s.get("sps_st", 1)))
    lines.append(
        f"It costs {slow:.1f}× the time process for process, and more in practice, "
        f"because spaCy scales across `build-corpus`'s workers and Stanza does not: "
        f"about {ceiling:.0f} sentences/s is the ceiling here however the work is "
        f"split, so a full teachable rebuild is roughly {314929 / ceiling / 60:.0f} "
        f"minutes against spaCy's {314929 / 700 / 60:.0f}, and every `add-video` pays "
        f"the same ratio. The `default_accurate` package is slower "
        f"again ({float(s.get('sps_acc', 0)):.0f} sentences/s) and no better — worse on "
        f"the override cases and prone to its own inventions (`Gibst` → `libsten`) — "
        f"so there is nothing to buy there.")
    lines.append(
        "Three ways to take it, in order of how much they touch:\n\n"
        "1. **Oracle.** Run Stanza offline over the corpus, keep spaCy at runtime, and "
        f"let the disagreements write the correction files: {s['candidate_overrides']} "
        f"override lines and {s['candidate_fixes']} fix lines from this sample alone, "
        "each needing a glance before it goes in (`danke → danken` is on the list, "
        "and must not go in). Zero runtime cost, and it turns a hand-hunt into a "
        "list.\n"
        "2. **Lemma source.** Keep spaCy's tokeniser, tagger and parser — the matcher "
        "reads TIGER labels and would break under UD's — and take the lemma from "
        "Stanza run pretokenised over spaCy's tokens, which this experiment shows "
        f"costs it nothing ({float(s['own_agrees_with_st']):.1%} agreement with its own "
        "tokenisation). Then normalise ß-spellings, keep the particle and contraction "
        "overrides, and re-resolve the vocabulary files, because the lemma space "
        "changes (`letzt` for `letzter`, `ich` for `mir`, `im` kept whole).\n"
        "3. **`spacy-stanza` wholesale.** Not recommended: it brings Stanza's "
        "tokeniser, with its multiword expansion, and UD dependency labels into a "
        "matcher written for TIGER's.")
    return "\n\n".join(lines)


def _history_table(history: list[dict]) -> str:
    columns = [("sentences", "sentences"), ("non-word md+repair", "nonword_md_repaired"),
               ("non-word Stanza", "nonword_st"), ("unreduced md+repair", "identity_verb_md_repaired"),
               ("unreduced Stanza", "identity_verb_st"), ("disagree", "disagree_share"),
               ("Stanza sent/s", "sps_st"), ("versions", "stanza")]
    head = "| run | " + " | ".join(label for label, _ in columns) + " |\n"
    head += "|---" * (len(columns) + 1) + "|\n"
    for record in history[-8:]:
        cells = " | ".join(str(record.get(key, "")) for _, key in columns)
        head += f"| {record['run_at'][:16].replace('T', ' ')} | {cells} |\n"
    return head


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run", help="parse the sample with every lemmatiser")
    runner.add_argument("--sample", type=int, default=6000)
    runner.add_argument("--transcript-share", type=float, default=0.25)
    probe = sub.add_parser("workers", help="Stanza throughput under worker processes")
    probe.add_argument("--sample", type=int, default=2000)
    sub.add_parser("analyse", help="cut the numbers and write the report")
    args = parser.parse_args()
    if args.command == "run":
        run(args.sample, args.transcript_share)
    elif args.command == "workers":
        workers(args.sample)
    else:
        analyse()


if __name__ == "__main__":
    main()
