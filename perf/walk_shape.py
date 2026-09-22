"""How big is the frontier scan, how much survives only_goals, and the native-hash ceiling."""
import sys, os, time, statistics, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from context import Application
from roadmap import CorpusIndex, RoadmapBuilder
from corpus.quality import well_formed
from vocab.entry import Unit

app = Application()
sentences = [s for s in app.corpus(strict=True) if well_formed(s.text)]
known = app.beginner_set(); targets = frozenset(app.goal_units)
idx = CorpusIndex(sentences, known, app.compounds)
b = RoadmapBuilder(idx, app.priority(), app.settings.priority_weight, targets,
                   only_goals=True, relax=False, video_minutes=app.video_minutes,
                   verdicts=app.verdicts(), judged=app.judged)

print("=== frontier scan shape (only_goals=True, the production mode) ===")
tot_scanned = tot_goal = 0
samples = []
for i in range(400):
    cands = idx.candidates()
    scanned = len(cands)
    goal_hits = sum(1 for u in cands if u in targets)
    tot_scanned += scanned; tot_goal += goal_hits
    if i % 80 == 0:
        print(f"  step {i:>4}: frontier {scanned:>6,}  of which goals {goal_hits:>4,}"
              f"  ({goal_hits/max(scanned,1)*100:4.1f}% survive the filter)")
    samples.append((scanned, goal_hits))
    st = b._next_step(i + 1)
    if st is None: break
    idx.learn(st.unit)
    if st.beside is not None: idx.learn(st.beside)
print(f"  over {len(samples)} steps: {tot_scanned:,} units scanned, {tot_goal:,} were goals"
      f"  -> {(1-tot_goal/tot_scanned)*100:.1f}% of the scan is discarded by `only_goals`")

print("\n=== native-hash ceiling: the same set/dict traffic, three key types ===")
keys_u = [Unit("lemma", f"w{i}") for i in range(3000)]
keys_t = [("lemma", f"w{i}") for i in range(3000)]
keys_i = list(range(3000))
def bench(keys, label, reps=400):
    d = {k: i for i, k in enumerate(keys)}
    s = set(keys[:1500])
    t = time.perf_counter()
    for _ in range(reps):
        g = d.get
        for k in keys:
            g(k); (k in s)
    el = time.perf_counter() - t
    n = reps * len(keys) * 2
    print(f"  {label:<34} {el:6.2f}s for {n:,} ops   {el/n*1e9:6.1f} ns/op")
    return el
a = bench(keys_u, "Unit (frozen dataclass, _hash)")
c = bench(keys_t, "plain tuple (C-level hash)")
d_ = bench(keys_i, "int id (C-level hash)")
print(f"\n  tuple vs Unit : {a/c:.2f}x faster       int vs Unit : {a/d_:.2f}x faster")
