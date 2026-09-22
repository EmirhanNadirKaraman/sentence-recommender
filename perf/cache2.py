"""Does the 4096-entry lru_cache thrash? Patch the module that is really used."""
import sys, os, time, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from functools import lru_cache
from context import Application
from corpus.analyzer import Evidence
app = Application(); store = app.corpus_store
with store._read() as cur:
    cur.execute("SELECT text FROM corpus_sentence WHERE build='subtitle' AND teachable ORDER BY id LIMIT 12000")
    texts = [r[0] for r in cur.fetchall()]
an = app.analyzer; _ = an.matcher.nlp; _ = an.verb_lemmas
docs = list(an.matcher.nlp.pipe(texts, batch_size=256))
pf = sys.modules["phrase_finder"]          # the copy actually executing
inner = pf.find_best_match.__wrapped__

def run(label, size):
    pf.find_best_match = lru_cache(maxsize=size)(inner)
    ev = Evidence()
    best = 1e9
    for _ in range(3):
        pf.find_best_match.cache_clear()
        t = time.perf_counter(); [an._units(d, ev) for d in docs]
        best = min(best, time.perf_counter() - t)
    ci = pf.find_best_match.cache_info()
    hr = ci.hits / max(ci.hits + ci.misses, 1) * 100
    print(f"  maxsize={str(size):<6} best {best:6.2f}s  hits {ci.hits:>6,} miss {ci.misses:>6,}"
          f"  hit-rate {hr:4.1f}%  size {ci.currsize:,}")
    return best

print("=== find_best_match cache sizing, 12,000 sentences, _units only ===")
a = run("4096", 4096)
b = run("65536", 65536)
c = run("None", None)
print(f"\n  4096 -> unbounded : {(a-c)/a*100:+.1f}% on _units")

# -- expression rows: cost of the 27 x tokens scan
import matcher.phrase_finder as mpf
print("\n=== find_expression_rows share of _units ===")
import cProfile, pstats, io
ev = Evidence()
pr = cProfile.Profile(); pr.enable(); [an._units(d, ev) for d in docs[:4000]]; pr.disable()
st = pstats.Stats(pr)
tot = sum(v[2] for v in st.stats.values())
for (fn, ln, nm), v in st.stats.items():
    if nm in ("find_expression_rows", "_match_row", "find_best_match", "extract_german_logic"):
        print(f"  {nm:<24} ncalls {v[1]:>9,}  tottime {v[2]:6.3f}s  cumtime {v[3]:6.3f}s")
