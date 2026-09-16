"""`embed-sentences` — ask the local model what each candidate sentence means.

Only the sentences the walk actually compares, which is far fewer than the
corpus: `spread` weighs the two dozen best candidates for a step against each
other, and nothing else is ever put side by side. That is 61,978 distinct
sentences against 309,964 in the corpus, and it is the difference between
twenty minutes and two hours.

Resumable, because it is twenty minutes over a tunnel and a dropped
connection should cost the last batch rather than the run. Everything already
stored is skipped, so running it again after a rebuild only asks about
sentences that are new.
"""
from __future__ import annotations

import sqlite3
import time

from corpus.vectors import DIMS, VectorStore, pack, without

BATCH = 128          # measured: 49.5 sentences a second, against 16.9 at 32
REPORT = 5_000
MODEL = "Qwen/Qwen3-Embedding-4B-GGUF"


class EmbedSentencesCommand:
    def run(self, app, label: str | None = None, model: str = MODEL,
            limit: int | None = None, batch: int = BATCH) -> None:
        from commands.export_deck import DEFAULT_LABEL     # noqa: PLC0415
        from generation.client import LLMClient            # noqa: PLC0415

        label = label or DEFAULT_LABEL
        settings = app.settings
        # The surface as well as the text: what is embedded is the sentence
        # with the taught word taken out, and the same sentence teaching a
        # different word is a different comparison.
        with sqlite3.connect(settings.state_path) as conn:
            rows = list(conn.execute(
                "SELECT DISTINCT text, surface FROM roadmap_example"
                " WHERE source = ?", (label,)))
        masked = {text: without(text, surface or "") for text, surface in rows}
        wanted = [text for text, _ in rows]
        if not wanted:
            raise SystemExit(f"no stored examples for '{label}' — "
                             "run `build-roadmap` first")

        store = VectorStore(settings.state_path)
        done = store.have()
        todo = [text for text in wanted if text not in done]
        if limit:
            todo = todo[:limit]
        print(f"{len(wanted):,} candidate sentences · {len(done):,} already "
              f"embedded · {len(todo):,} to do", flush=True)
        if not todo:
            print("nothing to do")
            return

        client = LLMClient(model=model, timeout=600)
        if not client.available:
            raise SystemExit("no local model configured — set LLM_BASE_URL")
        print(f"{client.describe()} · storing {DIMS} dims", flush=True)

        start = time.perf_counter()
        written = failed = 0
        for at in range(0, len(todo), batch):
            block = todo[at:at + batch]
            try:
                answer = client.embed([masked[text] for text in block])
            except Exception as error:                     # noqa: BLE001
                # One bad batch should not end a twenty-minute run; the
                # sentences in it stay unembedded and the next run picks
                # them up, because what is stored is what is skipped.
                failed += len(block)
                print(f"  ! batch at {at:,} failed: "
                      f"{type(error).__name__}: {error}"[:120], flush=True)
                continue
            store.add_many({text: pack(vector)
                            for text, vector in zip(block, answer)}, model)
            written += len(block)
            if written % REPORT < batch:
                rate = written / max(time.perf_counter() - start, 1e-9)
                left = (len(todo) - written) / rate / 60
                print(f"  … {written:,} of {len(todo):,} · {rate:.0f}/s · "
                      f"{left:.0f} min left", flush=True)

        spent = time.perf_counter() - start
        print(f"\nembedded {written:,} sentences in {spent / 60:.1f} min")
        if failed:
            print(f"  {failed:,} failed and are still owed — run it again")
        print(f"  {store.count():,} vectors stored")
