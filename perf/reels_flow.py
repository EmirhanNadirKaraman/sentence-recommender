"""The flow the reader actually takes: open Next, mark a word, open Reels.

Runs against a COPY of state.sqlite3 named on the command line, so nothing
real is marked or rescored. Read-only with respect to the project's own data.
"""
import sys, os, time, pathlib, resource
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
from dataclasses import replace
from config import Settings
from context import Application
from web.handlers import Viewer

LABEL, COPY, SRC = sys.argv[1], pathlib.Path(sys.argv[2]), "subtitle"
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
app = Application(replace(Settings(), state_path=COPY))
assert str(app.settings.state_path) == str(COPY)
print(f"### {LABEL}")

# --- settle the stored scores first, so the stamp starts valid
v0 = Viewer(app)
t = time.perf_counter(); v0._settled(SRC); print(f"  setup: first full scoring pass {time.perf_counter()-t:6.2f}s")
del v0

# --- scenario A: open Next, mark a word, open Reels
v = Viewer(app)
t = time.perf_counter(); idx = v.scope(SRC, list_only=False).index; a = time.perf_counter()-t
unit = max(((len(idx.containing(u)), u) for u in idx.candidates()), key=lambda p: p[0])[1]
t = time.perf_counter()
v.mark_known({"kind": unit.kind, "key": unit.key, "action": "known", "back": "/"})
v._marks.join()
b = time.perf_counter()-t
t = time.perf_counter(); rows = v._settled(SRC); c = time.perf_counter()-t
print(f"  A. open '/'                    {a:7.2f}s")
print(f"  A. mark {unit.key!r:<22} {b*1000:7.1f}ms  (incl. the background rescore)")
print(f"  A. click Reels                 {c:7.2f}s   rss {rss():6.0f} MB   {len(rows):,} videos")

# --- scenario B: a fresh process clicks Reels first
v2 = Viewer(app)
t = time.perf_counter(); rows2 = v2._settled(SRC); d = time.perf_counter()-t
loaded = len(v2._corpora) if hasattr(v2._corpora, "__len__") else "?"
print(f"  B. fresh process, Reels first  {d:7.2f}s   corpora loaded: {loaded}   {len(rows2):,} videos")
