"""Does gloss go faster with the slots the server actually has?

Real calls to the local endpoint, real cards — but the answers are written
to a THROWAWAY store, so the same cards can be asked twice and nothing
touches `data/state.sqlite3`. No paid API is involved: this is the local
LLM_BASE_URL model.
"""
import sys, os, time, pathlib, tempfile
ROOT = pathlib.Path("/Users/emir/Documents/GitHub/sentence-recommender")
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
from config import Settings, load_dotenv
load_dotenv()
from commands.export_deck import DEFAULT_LABEL
from deck import cards_from
from deck.gloss import GlossStore, missing, run
from generation.client import LLMClient
from roadmap.store import RoadmapStore

N = int(os.environ.get("N", "24"))
settings = Settings()
client = LLMClient(timeout=300)
model = os.environ.get("LLM_MODEL", "")
print(f"{client.describe()}   slots={client.slots()}")

plans = RoadmapStore(settings.state_path)
steps = plans.load(DEFAULT_LABEL, limit=N)
if not steps:
    raise SystemExit(f"no plan {DEFAULT_LABEL!r}; have {plans.labels()}")
decks = plans.decks(DEFAULT_LABEL, steps, limit=3)
# Empty senses and sentences, so every card counts as never asked and the
# same work can be run twice.
cards = cards_from(steps, decks, {}, {})
todo = missing(cards)
print(f"{len(cards)} cards, {len(todo)} to ask, "
      f"{sum(len(c.examples) for c in todo)} sentences\n")

results = {}
for workers in (2, 6, 2, 6):
    with tempfile.TemporaryDirectory() as tmp:
        store = GlossStore(pathlib.Path(tmp) / "throwaway.sqlite3")
        t = time.perf_counter()
        done, failed = run(list(cards), store, client, model,
                           answers=None, workers=workers)
        el = time.perf_counter() - t
    rate = done / el if el else 0
    ok = results.setdefault(workers, [])
    ok.append((el, done, failed, rate))
    print(f"  workers={workers}: {el:6.1f}s  {done} done  {failed} failed"
          f"  {rate:5.2f} cards/s", flush=True)

print()
for w in (2, 6):
    best = min(results[w], key=lambda r: r[0])
    fails = sum(r[2] for r in results[w])
    print(f"  workers={w}: best {best[0]:6.1f}s  {best[3]:5.2f} cards/s"
          f"  · failures across both runs: {fails}")
b2, b6 = min(r[0] for r in results[2]), min(r[0] for r in results[6])
print(f"\n  speedup {b2/b6:.2f}x")
print(f"  3,888 cards at that rate: {3888/(min(r[3] for r in results[2]) or 1)/60:.0f} min"
      f"  ->  {3888/(max(r[3] for r in results[6]) or 1)/60:.0f} min"
      f"   (measured in the chain: 82.5 min)")
