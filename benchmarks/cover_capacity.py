"""Read-only minimum-cover calculation: no saved lists or progress changes."""
import json
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Settings
from context import Application
from readers import Registry
from roadmap.cover import minimum_subset
from vocab.entry import Unit
from web.handlers import Viewer

owner = Registry().owner()
app = Application(Settings.for_reader(owner) if owner else Settings())
viewer = Viewer(app)
search = viewer._cover_search('subtitle')
known = viewer.known
goals = frozenset(app.goal_units) - known
ranked = [Unit(kind, key) for (kind, key), _ in sorted(search._said.items(), key=lambda row: -row[1])
          if Unit(kind, key) in goals]
minutes = dict(viewer._minutes())
results = []
for size in (20, 50, 100):
    chosen = frozenset(ranked[:size])
    start, cpu = time.perf_counter(), time.process_time()
    rows = app.corpus('subtitle', strict=True, holding_many=search.originals(chosen))
    fetched = time.perf_counter()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    cover, witnesses = minimum_subset(rows, known, chosen, minutes)
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    answer = {'targets': len(chosen), 'candidate_lines': len(rows),
              'fetch_ms': round((fetched-start)*1000, 2),
              'calculation_ms': round((time.perf_counter()-fetched)*1000, 2),
              'parent_cpu_ms': round((time.process_time()-cpu)*1000, 2),
              'solver_cpu_ms': round(((child_end.ru_utime+child_end.ru_stime)
                                      -(child_start.ru_utime+child_start.ru_stime))*1000, 2),
              'videos': len(cover.videos), 'covered': len(cover.taught), 'witnesses': len(witnesses),
              'unreachable': len(cover.unreachable), 'status': cover.status}
    results.append(answer)
    print(json.dumps(answer), flush=True)
Path(sys.argv[1]).write_text(json.dumps(results, indent=2)+'\n')
