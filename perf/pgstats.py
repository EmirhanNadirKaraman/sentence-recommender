import os, sys, psycopg2, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import Settings
conn = psycopg2.connect(**Settings().own.dsn_kwargs())
cur = conn.cursor()
def q(title, sql):
    print("=== " + title + " ===")
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    w = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c)) for i, c in enumerate(cols)]
    print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(cols)))
    for r in rows:
        print("  ".join(str(v).ljust(w[i]) for i, v in enumerate(r)))
    print()

q("version", "SELECT version()")
q("scan history (pg_stat_user_tables)", """
 SELECT relname, seq_scan, seq_tup_read, idx_scan, idx_tup_fetch,
        n_live_tup, n_dead_tup, last_autovacuum, last_analyze
 FROM pg_stat_user_tables ORDER BY seq_tup_read DESC""")
q("sizes", """
 SELECT relname,
        pg_size_pretty(pg_total_relation_size(c.oid)) AS total,
        pg_size_pretty(pg_relation_size(c.oid)) AS heap,
        pg_size_pretty(pg_indexes_size(c.oid)) AS idx
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind IN ('r','m')
 ORDER BY pg_total_relation_size(c.oid) DESC""")
q("pg_stat_statements available?", "SELECT count(*) FROM pg_available_extensions WHERE name='pg_stat_statements'")
q("pg_stat_statements installed?", "SELECT count(*) FROM pg_extension WHERE extname='pg_stat_statements'")
q("settings", "SELECT name, setting, unit FROM pg_settings WHERE name IN ('shared_buffers','work_mem','effective_cache_size','max_parallel_workers_per_gather','jit','random_page_cost')")
q("db size / stats reset", "SELECT pg_size_pretty(pg_database_size(current_database())) AS dbsize, stats_reset FROM pg_stat_database WHERE datname=current_database()")
q("builds", "SELECT build, count(*) FILTER (WHERE teachable) AS teachable, count(*) AS total FROM corpus_sentence GROUP BY build ORDER BY 3 DESC")
