"""Is track_goals' one-off snapshot actually costing a second?"""
import sys, os, time, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from context import Application
from roadmap import CorpusIndex
from corpus.quality import well_formed
app = Application()
sentences = [s for s in app.corpus(strict=True) if well_formed(s.text)]
known = app.beginner_set(); targets = frozenset(app.goal_units)
index = CorpusIndex(sentences, known, app.compounds)
print(f"frontier at step 0: {len(index.candidates()):,} units · goals {len(targets):,}")
best = 1e9
for _ in range(5):
    t = time.perf_counter(); index.track_goals(targets); best = min(best, time.perf_counter()-t)
print(f"track_goals(): best of 5 = {best*1000:.2f} ms  -> view holds {len(index.goal_candidates()):,}")
