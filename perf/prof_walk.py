"""The greedy walk alone: unprofiled scaling, then attribution. No store writes."""
import sys, os, time, cProfile, pstats, io, collections, resource, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from context import Application
from roadmap import CorpusIndex, RoadmapBuilder
from corpus.quality import well_formed

def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024*1024)

app = Application()
t = time.perf_counter(); sentences = app.corpus(strict=True); t_load = time.perf_counter()-t
sentences = [s for s in sentences if well_formed(s.text)]
known = app.beginner_set(); targets = frozenset(app.goal_units)
print(f"corpus {len(sentences):,} sentences loaded in {t_load:.2f}s · rss {rss():.0f} MB")

def fresh():
    idx = CorpusIndex(sentences, known, app.compounds)
    return RoadmapBuilder(idx, app.priority(), app.settings.priority_weight, targets,
                          only_goals=True, relax=False, video_minutes=app.video_minutes,
                          verdicts=app.verdicts(), judged=app.judged), idx

print("\n=== UNPROFILED walk, cumulative cost by step count ===")
b, idx = fresh()
prev_n = prev_t = 0
t0 = time.perf_counter()
for target in (100, 300, 600, 1200, 2400, 3902):
    more = b.build(max_steps=target - prev_n, first_position=prev_n + 1)
    if not more: print(f"  walk exhausted at {prev_n} steps"); break
    prev_n += len(more)
    el = time.perf_counter() - t0
    seg = el - prev_t
    print(f"  {prev_n:>5,} steps  cumulative {el:7.2f}s   this segment {seg:6.2f}s"
          f"   {seg/len(more)*1000:6.1f} ms/step   readable {idx.readable:,}")
    prev_t = el
walk_total = time.perf_counter() - t0
print(f"  full walk: {walk_total:.2f}s for {prev_n:,} steps · rss {rss():.0f} MB")

print("\n=== PROFILED walk (600 steps) — attribution ===")
b2, _ = fresh()
pr = cProfile.Profile(); pr.enable()
t = time.perf_counter(); b2.build(max_steps=600); tp = time.perf_counter()-t
pr.disable()
print(f"  profiled 600 steps: {tp:.2f}s (profiler inflates; unprofiled above is the truth)")
st = pstats.Stats(pr); buckets = collections.Counter()
for (fn, ln, nm), v in st.stats.items():
    if ".venv" in fn: b_ = "native/pkg:" + fn.split("site-packages/")[-1].split("/")[0]
    elif "sentence-recommender" in fn: b_ = "python:" + fn.split("sentence-recommender/")[-1].split("/")[0]
    elif fn == "~" or fn.startswith("<"): b_ = "C-builtin (dict/set/len/hash)"
    else: b_ = "stdlib"
    buckets[b_] += v[2]
tot = sum(buckets.values())
for k, v in buckets.most_common(8):
    print(f"    {k:<32} {v:7.3f}s  {v/tot*100:5.1f}%")
s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(14)
print("\n  --- top 14 by tottime ---"); print("\n".join("  "+l for l in s.getvalue().splitlines()[4:22]))
