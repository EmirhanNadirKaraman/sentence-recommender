"""spaCy analysis cost, on a fixed slice of real sentences. Writes nothing."""
import sys, os, time, cProfile, pstats, io, collections, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
N = int(os.environ.get("N", "5000"))
from context import Application
from corpus.analyzer import Evidence

app = Application()
store = app.corpus_store
t = time.perf_counter()
with store._read() as cur:
    cur.execute("SELECT text FROM corpus_sentence WHERE build='subtitle'"
                " AND teachable ORDER BY id LIMIT %s", (N,))
    texts = [r[0] for r in cur.fetchall()]
print(f"fetched {len(texts):,} texts in {time.perf_counter()-t:.2f}s")
print(f"mean length {sum(len(x) for x in texts)/len(texts):.0f} chars\n")

print("=== model load (cold, this process) ===")
t = time.perf_counter()
an = app.analyzer
_ = an.matcher.nlp
t_model = time.perf_counter() - t
print(f"  UnitAnalyzer + spaCy de_core_news_md : {t_model:7.2f}s")
t = time.perf_counter(); _ = an.verb_lemmas; t_vl = time.perf_counter()-t
print(f"  verb_lemmas table                    : {t_vl:7.2f}s")

print("\n=== parse only (nlp.pipe), 1 process ===")
t = time.perf_counter()
docs = list(an.matcher.nlp.pipe(texts, batch_size=256))
t_parse = time.perf_counter() - t
print(f"  {t_parse:7.2f}s   {len(texts)/t_parse:6.0f} sent/s")

print("\n=== units off the parsed docs, 1 process (profiled) ===")
ev = Evidence()
pr = cProfile.Profile(); pr.enable()
t = time.perf_counter()
found = [an._units(d, ev) for d in docs]
t_units = time.perf_counter() - t
pr.disable()
print(f"  {t_units:7.2f}s   {len(texts)/t_units:6.0f} sent/s")

st = pstats.Stats(pr); buckets = collections.Counter()
for (fn, ln, name), (cc, nc, tt, ct, cal) in st.stats.items():
    if ".venv" in fn:   b = "pkg:" + fn.split("site-packages/")[-1].split("/")[0]
    elif "sentence-recommender" in fn: b = "project:" + fn.split("sentence-recommender/")[-1].split("/")[0]
    elif fn == "~" or fn.startswith("<"): b = "builtin/C"
    else: b = "stdlib"
    buckets[b] += tt
tot = sum(buckets.values())
print(f"\n  --- _units() tottime by bucket ({tot:.2f}s profiled) ---")
for b, v in buckets.most_common(8):
    print(f"    {b:<30} {v:7.3f}s  {v/tot*100:5.1f}%")
s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(10)
print("  --- top 10 ---"); print("\n".join("  "+l for l in s.getvalue().splitlines()[4:18]))

print(f"\n=== 1-process totals for {N:,} sentences ===")
print(f"  parse {t_parse:.2f}s + units {t_units:.2f}s = {t_parse+t_units:.2f}s"
      f"  ({N/(t_parse+t_units):.0f} sent/s)")
print(f"  parse share of that: {t_parse/(t_parse+t_units)*100:.0f}%")
