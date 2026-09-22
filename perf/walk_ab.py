"""One production walk: time it, and fingerprint the plan it produced.

Run once on the changed tree and once on HEAD's, and the two outputs are the
before/after. Writes nothing to any store.
"""
import sys, os, time, json, hashlib, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
LABEL = sys.argv[1]
OUT = sys.argv[2]
# `relax` exercises `_relaxed_step`, the branch that takes two words from
# one sentence when nothing anywhere is one word away. It scans the
# lookahead rather than the frontier, so it is the path the goal view
# does not cover — and therefore the one worth hashing separately.
RELAX = len(sys.argv) > 3 and sys.argv[3] == "relax"

from context import Application
from roadmap import CorpusIndex, RoadmapBuilder
from corpus.quality import well_formed

T = time.perf_counter()
app = Application()
t = time.perf_counter(); sentences = app.corpus(strict=True); t_load = time.perf_counter()-t
sentences = [s for s in sentences if well_formed(s.text)]
known = app.beginner_set(); targets = frozenset(app.goal_units)

t = time.perf_counter()
index = CorpusIndex(sentences, known, app.compounds)
t_index = time.perf_counter()-t

t = time.perf_counter()
builder = RoadmapBuilder(index, app.priority(), app.settings.priority_weight,
                         targets, only_goals=True, relax=RELAX,
                         video_minutes=app.video_minutes,
                         verdicts=app.verdicts(), judged=app.judged)
t_builder = time.perf_counter()-t

t = time.perf_counter()
plan = builder.build()
t_walk = time.perf_counter()-t
t_total = time.perf_counter()-T

fp = hashlib.sha256()
rows = []
for s in plan:
    row = [s.position, s.unit.kind, s.unit.key, round(s.score, 9), s.gain,
           s.sentence.text if s.sentence else "", s.now_readable, s.readable,
           tuple(e.text for e in s.examples)]
    rows.append(row)
    fp.update(repr(row).encode())

result = {
    "label": LABEL, "relax": RELAX,
    "sentences": len(sentences), "steps": len(plan),
    "load_s": round(t_load, 3), "index_s": round(t_index, 3),
    "builder_s": round(t_builder, 3), "walk_s": round(t_walk, 3),
    "total_s": round(t_total, 3),
    "ms_per_step": round(t_walk / max(len(plan), 1) * 1000, 3),
    "readable_at_end": index.readable,
    "plan_sha256": fp.hexdigest(),
    "first_10": [(r[2], r[5][:40]) for r in rows[:10]],
    "last_5": [(r[2], r[5][:40]) for r in rows[-5:]],
}
json.dump(result, open(OUT, "w"), indent=1)
print(json.dumps({k: v for k, v in result.items()
                  if k not in ("first_10", "last_5")}, indent=1))
