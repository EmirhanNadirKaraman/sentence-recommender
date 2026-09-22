"""What does the non-goal skip path in _next_step actually cost?

Measures the real loop's two guard checks over the real frontier, against
the same loop restricted to goals. The difference is exactly what an
incrementally-maintained goal-candidate view would remove.
"""
import sys, os, time, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from context import Application
from roadmap import CorpusIndex, RoadmapBuilder
from corpus.quality import well_formed

app = Application()
sentences = [s for s in app.corpus(strict=True) if well_formed(s.text)]
known = app.beginner_set(); targets = frozenset(app.goal_units)
idx = CorpusIndex(sentences, known, app.compounds)
b = RoadmapBuilder(idx, app.priority(), app.settings.priority_weight, targets,
                   only_goals=True, relax=False, video_minutes=app.video_minutes,
                   verdicts=app.verdicts(), judged=app.judged)

EXCLUDE = frozenset(); KINDS = frozenset()
def full_scan(cands, goals):
    """Exactly the guard sequence in builder.py:154, over the whole frontier."""
    n = 0
    for unit, positions in cands.items():
        if not positions or unit in EXCLUDE: continue
        if unit not in goals: continue
        n += 1
    return n
def goal_scan(goal_cands):
    n = 0
    for unit, positions in goal_cands.items():
        if not positions or unit in EXCLUDE: continue
        n += 1
    return n

print(f"{'step':>5} {'frontier':>9} {'goals':>7}  {'full scan':>10} {'goal-only':>10} {'saved':>8}")
samples = []
for i in range(600):
    if i in (50, 150, 300, 450, 599):
        cands = idx.candidates()
        goal_cands = {u: p for u, p in cands.items() if u in targets}
        R = 200
        t = time.perf_counter()
        for _ in range(R): full_scan(cands, targets)
        t_full = (time.perf_counter() - t) / R
        t = time.perf_counter()
        for _ in range(R): goal_scan(goal_cands)
        t_goal = (time.perf_counter() - t) / R
        samples.append((t_full, t_goal))
        print(f"{i:>5} {len(cands):>9,} {len(goal_cands):>7,}  "
              f"{t_full*1000:>9.2f}ms {t_goal*1000:>9.2f}ms {(t_full-t_goal)*1000:>7.2f}ms")
    st = b._next_step(i + 1)
    if st is None: break
    idx.learn(st.unit)
    if st.beside is not None: idx.learn(st.beside)

mean_saved = sum(f - g for f, g in samples) / len(samples)
print(f"\n  mean saved per step : {mean_saved*1000:.2f} ms")
print(f"  over 3,902 steps    : {mean_saved*3902:.2f} s")
print(f"  walk measured at      30.51 s  ->  {mean_saved*3902/30.51*100:.1f}% of the walk")
print(f"  projected walk        {30.51 - mean_saved*3902:.1f} s")
