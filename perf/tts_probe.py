"""Is piper already using the cores? Sequential vs a process pool. Local, free."""
import sys, os, time, pathlib, resource
ROOT = pathlib.Path("/Users/emir/Documents/GitHub/sentence-recommender")
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)

def texts(n):
    from context import Application
    app = Application()
    with app.corpus_store._read() as cur:
        cur.execute("SELECT text FROM corpus_sentence WHERE build='subtitle'"
                    " AND teachable AND length(text) BETWEEN 40 AND 90"
                    " ORDER BY id LIMIT %s", (n,))
        return [r[0] for r in cur.fetchall()]

def cpu_time():
    me = resource.getrusage(resource.RUSAGE_SELF)
    kids = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (me.ru_utime + me.ru_stime + kids.ru_utime + kids.ru_stime)

_V = None
def _say(text):
    global _V
    if _V is None:
        from deck.speech import PiperSpeaker, DEFAULT_GERMAN
        _V = PiperSpeaker(DEFAULT_GERMAN)
    return len(_V.pcm(text))

def main():
    lines = texts(48)
    print(f"{len(lines)} real lines, mean {sum(map(len,lines))//len(lines)} chars")
    from deck.speech import PiperSpeaker, DEFAULT_GERMAN
    t = time.perf_counter(); v = PiperSpeaker(DEFAULT_GERMAN); load = time.perf_counter()-t
    print(f"  voice load: {load:.2f}s   sample_rate {v.sample_rate}")

    c0, w0 = cpu_time(), time.perf_counter()
    for x in lines: v.pcm(x)
    seq_w, seq_c = time.perf_counter()-w0, cpu_time()-c0
    print(f"  sequential : {seq_w:6.2f}s wall  {seq_c:6.2f}s cpu"
          f"   -> {seq_c/seq_w:.2f} cores busy   {len(lines)/seq_w:5.2f} lines/s")

    from concurrent.futures import ProcessPoolExecutor
    for procs in (2, 4):
        c0, w0 = cpu_time(), time.perf_counter()
        with ProcessPoolExecutor(max_workers=procs) as pool:
            list(pool.map(_say, lines, chunksize=4))
        w, c = time.perf_counter()-w0, cpu_time()-c0
        print(f"  pool of {procs}  : {w:6.2f}s wall  {c:6.2f}s cpu"
              f"   -> {c/w:.2f} cores busy   {len(lines)/w:5.2f} lines/s"
              f"   {seq_w/w:.2f}x")

if __name__ == "__main__":
    main()
