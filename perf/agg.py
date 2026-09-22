"""Where inside load() the Python time goes, and whether SQL aggregation beats it."""
import sys, os, time, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from context import Application
from vocab.entry import Unit
app = Application(); store = app.corpus_store
conn = store._conn(); B = list(store.builds())
WHERE = " WHERE s.build = ANY(%s) AND (s.language IS NULL OR s.language='de')"

def run(label, sql, args, consume):
    with conn.cursor() as c:
        t = time.perf_counter(); c.execute(sql, args); t_exec = time.perf_counter() - t
        t = time.perf_counter(); n, out = consume(c); t_con = time.perf_counter() - t
    print(f"  {label:<40} exec {t_exec:6.3f}s  consume {t_con:6.3f}s  total {t_exec+t_con:6.3f}s  ({n:,} rows)")
    return out

print("=== current: 3.18M unit rows, dict/set build in Python ===")
def cur_consume(c):
    units, surfaces, seen, unseen = {}, {}, {}, object()
    n = 0
    for sid, kind, key, surface in c:
        n += 1
        u = seen.get((kind, key), unseen)
        if u is unseen:
            u = seen[(kind, key)] = Unit(kind, key)
        units.setdefault(sid, set()).add(u)
        if surface:
            surfaces.setdefault(sid, []).append((u, surface))
    return n, (units, surfaces)
cur = run("row-at-a-time (as shipped)",
    "SELECT su.sentence_id, su.kind, su.key, su.surface FROM corpus_unit su"
    " JOIN corpus_sentence s ON s.id=su.sentence_id" + WHERE, (B,), cur_consume)

print("\n=== variant 1: ORDER BY sentence_id + groupby (no setdefault) ===")
from itertools import groupby
from operator import itemgetter
def grp_consume(c):
    units, surfaces, seen, n = {}, {}, {}, 0
    for sid, rows in groupby(c, itemgetter(0)):
        s = set(); sf = []
        for _, kind, key, surface in rows:
            n += 1
            u = seen.get((kind, key))
            if u is None: u = seen[(kind, key)] = Unit(kind, key)
            s.add(u)
            if surface: sf.append((u, surface))
        units[sid] = frozenset(s)
        if sf: surfaces[sid] = tuple(sf)
    return n, (units, surfaces)
run("ORDER BY sid + itertools.groupby",
    "SELECT su.sentence_id, su.kind, su.key, su.surface FROM corpus_unit su"
    " JOIN corpus_sentence s ON s.id=su.sentence_id" + WHERE
    + " ORDER BY su.sentence_id", (B,), grp_consume)

print("\n=== variant 2: server-side array_agg, 310k rows ===")
def arr_consume(c):
    units, surfaces, seen, n = {}, {}, {}, 0
    for sid, kinds, keys, surfs in c:
        s = set(); sf = []
        for i, key in enumerate(keys):
            n += 1
            kk = (kinds[i], key)
            u = seen.get(kk)
            if u is None: u = seen[kk] = Unit(*kk)
            s.add(u)
            sv = surfs[i]
            if sv: sf.append((u, sv))
        units[sid] = frozenset(s)
        if sf: surfaces[sid] = tuple(sf)
    return n, (units, surfaces)
run("array_agg(kind),array_agg(key),...",
    "SELECT su.sentence_id, array_agg(su.kind), array_agg(su.key),"
    " array_agg(coalesce(su.surface,'')) FROM corpus_unit su"
    " JOIN corpus_sentence s ON s.id=su.sentence_id" + WHERE
    + " GROUP BY su.sentence_id", (B,), arr_consume)

print("\n=== variant 3: string_agg into one text blob per sentence ===")
def str_consume(c):
    units, surfaces, seen, n = {}, {}, {}, 0
    for sid, blob in c:
        s = set(); sf = []
        for rec in blob.split("\x1e"):
            n += 1
            kind, _, rest = rec.partition("\x1f")
            key, _, surface = rest.partition("\x1f")
            kk = (kind, key)
            u = seen.get(kk)
            if u is None: u = seen[kk] = Unit(kind, key)
            s.add(u)
            if surface: sf.append((u, surface))
        units[sid] = frozenset(s)
        if sf: surfaces[sid] = tuple(sf)
    return n, (units, surfaces)
run("string_agg(kind|key|surface)",
    "SELECT su.sentence_id,"
    " string_agg(su.kind||E'\\x1f'||su.key||E'\\x1f'||coalesce(su.surface,''), E'\\x1e')"
    " FROM corpus_unit su JOIN corpus_sentence s ON s.id=su.sentence_id" + WHERE
    + " GROUP BY su.sentence_id", (B,), str_consume)

print("\n=== variant 4: current query, consume but DISCARD (pure transfer cost) ===")
def drain(c):
    n = 0
    for _ in c: n += 1
    return n, None
run("transfer only, no objects",
    "SELECT su.sentence_id, su.kind, su.key, su.surface FROM corpus_unit su"
    " JOIN corpus_sentence s ON s.id=su.sentence_id" + WHERE, (B,), drain)
