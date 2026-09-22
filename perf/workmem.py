import os, sys, time, statistics, psycopg2, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import Settings
conn = psycopg2.connect(**Settings().own.dsn_kwargs()); conn.autocommit = True
cur = conn.cursor()
BUILDS = ['generated', 'subtitle', 'transcript']

UNIT_JOIN = ("SELECT su.sentence_id, su.kind, su.key, su.surface FROM corpus_unit su"
             " JOIN corpus_sentence s ON s.id = su.sentence_id"
             " WHERE s.build = ANY(%s) AND (s.language IS NULL OR s.language='de')")

def timeit(sql, args, n=3, fetch=True):
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        cur.execute(sql, args)
        if fetch: cur.fetchall()
        ts.append(time.perf_counter() - t)
    return min(ts), statistics.median(ts)

print("### full unit join, fetched into Python, by work_mem")
for wm in ('4MB', '16MB', '64MB', '256MB'):
    cur.execute(f"SET work_mem = '{wm}'")
    lo, md = timeit(UNIT_JOIN, (BUILDS,))
    print(f"  work_mem={wm:>6}  min {lo*1000:7.0f} ms   median {md*1000:7.0f} ms")

print()
print("### plan shape at 64MB")
cur.execute("SET work_mem='64MB'")
cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + UNIT_JOIN, (BUILDS,))
for (l,) in cur.fetchall(): print("   " + l)

print()
print("### matview group by work_mem")
MV = ("SELECT kind, key, sum(said)::int FROM corpus_unit_count"
      " WHERE build = ANY(%s) GROUP BY kind, key")
for wm in ('4MB', '64MB'):
    cur.execute(f"SET work_mem = '{wm}'")
    lo, md = timeit(MV, (BUILDS,), n=5)
    print(f"  work_mem={wm:>6}  min {lo*1000:7.1f} ms   median {md*1000:7.1f} ms")
