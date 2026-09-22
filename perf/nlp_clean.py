"""Unprofiled parse/units split + where find_best_match really lives."""
import sys, os, time, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from context import Application
from corpus.analyzer import Evidence
app = Application(); store = app.corpus_store
with store._read() as cur:
    cur.execute("SELECT text FROM corpus_sentence WHERE build='subtitle' AND teachable ORDER BY id LIMIT 12000")
    texts = [r[0] for r in cur.fetchall()]
an = app.analyzer; _ = an.matcher.nlp; _ = an.verb_lemmas

# which module object is actually executing?
import matcher.phrase_finder as pf
mods = [m for n, m in sys.modules.items() if n.endswith("phrase_finder") and m]
print("phrase_finder module objects loaded:", [getattr(m,'__name__',None) for m in mods])
print("analyzer's matcher class module:", type(an.matcher).__module__)

for m in mods:
    if hasattr(m, "find_best_match"): m.find_best_match.cache_clear()

print(f"\n=== unprofiled, {len(texts):,} sentences, 1 process ===")
t = time.perf_counter(); docs = list(an.matcher.nlp.pipe(texts, batch_size=256)); tp = time.perf_counter()-t
ev = Evidence()
t = time.perf_counter(); found = [an._units(d, ev) for d in docs]; tu = time.perf_counter()-t
tot = tp + tu
print(f"  spaCy parse (Cython/native) : {tp:6.2f}s  {len(texts)/tp:5.0f} sent/s  {tp/tot*100:5.1f}%")
print(f"  _units  (project Python)    : {tu:6.2f}s  {len(texts)/tu:5.0f} sent/s  {tu/tot*100:5.1f}%")
print(f"  combined                    : {tot:6.2f}s  {len(texts)/tot:5.0f} sent/s")
for m in mods:
    if hasattr(m, "find_best_match"):
        print(f"  {m.__name__}.find_best_match {m.find_best_match.cache_info()}")

# second pass (the corpus-wide vote) -- the other half of analyze_all
from corpus.sentence import Sentence
sents = [Sentence(text=x, origin="subtitle") for x in texts]
analysed = [s.with_units(u, sf) for s, (u, sf) in zip(sents, found)]
t = time.perf_counter()
corr = an._lemma_corrections(ev)
an._normalise(analysed, an._proper_nouns(ev), {**corr, **an._prefixed_corrections(ev, corr)})
tn = time.perf_counter()-t
print(f"\n  second pass (_normalise/vote) : {tn:6.2f}s  ({tn/(tot+tn)*100:.1f}% of {tot+tn:.2f}s)")
