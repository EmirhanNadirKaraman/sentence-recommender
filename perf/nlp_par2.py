import sys, os, time, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
def main():
    from context import Application
    from corpus.sentence import Sentence
    from corpus import parallel
    app = Application(); store = app.corpus_store
    with store._read() as cur:
        cur.execute("SELECT text FROM corpus_sentence WHERE build='subtitle'"
                    " AND teachable ORDER BY id LIMIT 24000")
        texts = [r[0] for r in cur.fetchall()]
    an = app.analyzer; _ = an.matcher.nlp; _ = an.verb_lemmas
    sents = [Sentence(text=x, origin="subtitle") for x in texts]
    import platform
    print(f"{len(sents):,} sentences · {platform.processor()} · {os.cpu_count()} logical cores")
    try:
        import subprocess
        p = subprocess.run(["sysctl","-n","hw.perflevel0.logicalcpu","hw.perflevel1.logicalcpu"],
                           capture_output=True, text=True)
        print(f"  performance cores / efficiency cores: {p.stdout.split()}")
    except Exception: pass
    res = {}
    for rep in range(3):
        for procs in (4, 6, 8):
            t = time.perf_counter()
            parallel.analyze_all(an, sents, processes=procs)
            el = time.perf_counter() - t
            res.setdefault(procs, []).append(len(texts)/el)
            print(f"  rep{rep+1} procs={procs}: {el:6.2f}s  {len(texts)/el:5.0f} sent/s", flush=True)
    print("\n=== best of 3 ===")
    for procs, rates in sorted(res.items()):
        print(f"  processes={procs}: best {max(rates):5.0f} sent/s   "
              f"262k-sentence build ≈ {262000/max(rates)/60:.1f} min")
if __name__ == "__main__":
    main()
