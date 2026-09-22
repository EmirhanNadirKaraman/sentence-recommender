"""Break app.corpus() into SQL / row-transfer / Python-object phases."""
import sys, os, time, cProfile, pstats, io, collections, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from context import Application

app = Application()
store = app.corpus_store
builds = tuple(store.builds())
print("builds:", builds)

# --- A. raw server+transfer cost of the two queries, isolated
conn = store._conn()
def raw(sql, args, label, n=2):
    best = 1e9
    for _ in range(n):
        with conn.cursor() as c:
            t = time.perf_counter(); c.execute(sql, args); rows = c.fetchall()
            best = min(best, time.perf_counter() - t)
    print(f"  {label:<44} {best:7.3f}s   ({len(rows):,} rows)")
    return best

print("\n=== A. the two SQL queries alone (psycopg2 fetchall) ===")
B = list(builds)
q_sent = ("SELECT id, origin, text, translation, raw_text, source_ids, video_id,"
          " start_time, end_time, teachable FROM corpus_sentence"
          " WHERE build = ANY(%s) AND teachable AND (language IS NULL OR language='de')")
q_unit = ("SELECT su.sentence_id, su.kind, su.key, su.surface FROM corpus_unit su"
          " JOIN corpus_sentence s ON s.id = su.sentence_id"
          " WHERE s.build = ANY(%s) AND (s.language IS NULL OR s.language='de')")
a1 = raw(q_sent, (B,), "sentence rows")
a2 = raw(q_unit, (B,), "unit join rows")

# --- B. CorpusStore.load with no resolve (pure object building)
print("\n=== B. CorpusStore.load(), no resolve ===")
t = time.perf_counter(); s0 = store.load(*builds); b1 = time.perf_counter() - t
print(f"  {'store.load(no resolve)':<44} {b1:7.3f}s   ({len(s0):,} sentences)")

# --- C. full app.corpus(strict=True), profiled
print("\n=== C. app.corpus(strict=True), profiled ===")
app2 = Application()
_ = app2.check_freshness            # warm the freshness check out of the profile
_ = app2._unit_rule(True, False)    # warm aliases/goal resolution out of it
pr = cProfile.Profile(); pr.enable()
t = time.perf_counter(); sents = app2.corpus(strict=True); c1 = time.perf_counter() - t
pr.disable()
print(f"  {'app.corpus(strict=True)':<44} {c1:7.3f}s   ({len(sents):,} sentences)")

st = pstats.Stats(pr)
buckets = collections.Counter()
for (fn, ln, name), (cc, nc, tt, ct, cal) in st.stats.items():
    if ".venv" in fn:
        b = "pkg:" + fn.split("site-packages/")[-1].split("/")[0]
    elif "sentence-recommender" in fn:
        b = "project:" + fn.split("sentence-recommender/")[-1].split("/")[0]
    elif fn == "~" or fn.startswith("<"):
        b = "builtin/C"
    else:
        b = "stdlib"
    buckets[b] += tt
tot = sum(buckets.values())
print(f"\n--- tottime by bucket (profiled total {tot:.2f}s) ---")
for b, v in buckets.most_common(12):
    print(f"  {b:<32} {v:7.3f}s  {v/tot*100:5.1f}%")
print("\n--- top 20 by tottime ---")
s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(20)
print("\n".join(s.getvalue().splitlines()[4:30]))

print("\n=== SUMMARY ===")
print(f"  SQL+transfer (A1+A2)            {a1+a2:7.3f}s")
print(f"  store.load total (B)            {b1:7.3f}s  -> python object build {b1-(a1+a2):+.3f}s")
print(f"  app.corpus total (C)            {c1:7.3f}s  -> resolve+overrides   {c1-b1:+.3f}s")
