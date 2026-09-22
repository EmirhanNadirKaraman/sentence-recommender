import os, sys, time, psycopg2, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import Settings
conn = psycopg2.connect(**Settings().own.dsn_kwargs()); conn.autocommit = True
cur = conn.cursor()
BUILDS = ['generated', 'subtitle', 'transcript']

def explain(title, sql, args, runs=2):
    print("=" * 70); print(title)
    for i in range(runs):
        t = time.perf_counter()
        cur.execute("EXPLAIN (ANALYZE, BUFFERS, TIMING) " + sql, args)
        plan = cur.fetchall()
        el = time.perf_counter() - t
        print(f"-- run {i+1}: {el*1000:.0f} ms wall")
        if i == runs - 1:
            for (line,) in plan: print("   " + line)
    print()

# 1. the sentence half of load()
explain("load(): sentence rows",
  "SELECT id, origin, text, translation, raw_text, source_ids, video_id,"
  " start_time, end_time, teachable FROM corpus_sentence"
  " WHERE build = ANY(%s) AND teachable AND (language IS NULL OR language='de')",
  (BUILDS,))

# 2. the unit half of load() -- the 3.18M-row join
explain("load(): unit join (the big one)",
  "SELECT su.sentence_id, su.kind, su.key, su.surface FROM corpus_unit su"
  " JOIN corpus_sentence s ON s.id = su.sentence_id"
  " WHERE s.build = ANY(%s) AND (s.language IS NULL OR s.language='de')",
  (BUILDS,))

# 3. unit_counts off the matview
explain("unit_counts(): matview group",
  "SELECT kind, key, sum(said)::int FROM corpus_unit_count"
  " WHERE build = ANY(%s) GROUP BY kind, key", (BUILDS,))
