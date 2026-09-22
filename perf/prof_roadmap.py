"""Phase-timed, cProfile'd build-roadmap walk. Writes nothing to any store."""
import sys, os, time, cProfile, pstats, io, collections, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

STEPS = int(os.environ.get("STEPS", "300"))
PROFILE = os.environ.get("PROFILE", "1") == "1"

marks = []
def mark(label, t0):
    t = time.perf_counter()
    marks.append((label, t - t0))
    print(f"  {label:<38} {t-t0:7.3f}s", flush=True)
    return t

print(f"=== build-roadmap walk, {STEPS} steps (no store write) ===")
T = t0 = time.perf_counter()
from context import Application
from roadmap import CorpusIndex, RoadmapBuilder
from corpus.quality import well_formed
t0 = mark("import project modules", t0)

app = Application()
t0 = mark("Application()", t0)

sentences = app.corpus(strict=True)          # strict => goals, the real default
t0 = mark("app.corpus(strict=True)  [DB+py]", t0)
print(f"      -> {len(sentences):,} sentences")

before = len(sentences)
sentences = [s for s in sentences if well_formed(s.text)]
t0 = mark("quality filter well_formed()", t0)
print(f"      -> {len(sentences):,} of {before:,}")

known = app.beginner_set()
t0 = mark("app.beginner_set()  [spaCy?]", t0)

targets = frozenset(app.goal_units)
t0 = mark("app.goal_units", t0)

compounds = app.compounds
t0 = mark("app.compounds", t0)

index = CorpusIndex(sentences, known, compounds)
t0 = mark("CorpusIndex(...)", t0)

prio = app.priority()
t0 = mark("app.priority()", t0)
vmin = app.video_minutes
t0 = mark("app.video_minutes", t0)
verd = app.verdicts()
t0 = mark("app.verdicts()", t0)
judged = app.judged
t0 = mark("app.judged", t0)

builder = RoadmapBuilder(index, prio, app.settings.priority_weight, targets,
                         only_goals=True, relax=False,
                         video_minutes=vmin, verdicts=verd, judged=judged)
t0 = mark("RoadmapBuilder.__init__ (gaps)", t0)

if PROFILE:
    pr = cProfile.Profile(); pr.enable()
walk_t = time.perf_counter()
plan = builder.build(max_steps=STEPS)
walk = time.perf_counter() - walk_t
if PROFILE:
    pr.disable()
t0 = mark(f"builder.build({STEPS})", t0)
print(f"      -> {len(plan)} steps, {walk/max(len(plan),1)*1000:.1f} ms/step")

total = time.perf_counter() - T
print(f"  {'TOTAL':<38} {total:7.3f}s")

if PROFILE:
    st = pstats.Stats(pr)
    # aggregate tottime by module bucket
    buckets = collections.Counter()
    for (fn, ln, name), (cc, nc, tt, ct, cal) in st.stats.items():
        if fn.startswith("<repo root>/.venv"):
            parts = fn.split("site-packages/")[-1].split("/")
            b = "pkg:" + parts[0]
        elif fn.startswith("<repo root>"):
            b = "project:" + fn.split("sentence-recommender/")[-1].split("/")[0]
        elif fn == "~" or fn.startswith("<"):
            b = "builtin"
        else:
            b = "stdlib"
        buckets[b] += tt
    print(f"\n=== WALK ONLY: cProfile tottime by bucket (total {sum(buckets.values()):.2f}s) ===")
    for b, v in buckets.most_common(14):
        print(f"  {b:<34} {v:7.3f}s  {v/sum(buckets.values())*100:5.1f}%")
    print("\n=== WALK ONLY: top 22 by tottime ===")
    s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(22)
    print("\n".join(s.getvalue().splitlines()[4:34]))
