"""`fill-gaps` — generate the examples the corpus cannot supply.

Some roadmap steps have no sentence that is i+1 against what the learner knows
at that point: every corpus sentence using the word drags in two or three
other unknowns.  A card with no readable example is barely a card, so the
local model writes one.

The known set is replayed step by step rather than taken from the end of the
roadmap.  Step 40's example has to be readable with what was known at step 40;
judging it against the finished vocabulary would call gaps filled that are not.
"""
from __future__ import annotations

from corpus.sentence import GENERATED
from generation import LLMClient, SentenceGenerator
from roadmap import ExampleIndex, RoadmapStore

# How much of the known vocabulary to put in the prompt.  The whole set runs to
# thousands of words; the most frequent few hundred is what a simple sentence
# is built from anyway, and it leaves room for the model to answer.
VOCABULARY_SAMPLE = 250


class FillGapsCommand:
    def run(self, app, limit: int | None = None,
            builds: tuple[str, ...] = ()) -> None:
        settings = app.settings
        steps = RoadmapStore(settings.state_path).load()
        if not steps:
            raise SystemExit("no roadmap — run `build-roadmap` first")

        client = LLMClient(timeout=settings.llm_timeout)
        if not client.available:
            raise SystemExit(
                "no local model configured — set LLM_BASE_URL and LLM_MODEL in .env"
            )

        sentences = app.corpus(*builds)
        examples = ExampleIndex(sentences)
        priority = app.priority()
        known = app.known_set()
        generator = SentenceGenerator(client, app.analyzer)

        produced, gaps = [], 0
        for step in steps:
            if limit is not None and len(produced) >= limit:
                break
            if not self._has_readable_example(examples, step.unit, known.units):
                gaps += 1
                print(f"  {step.position:>4}. {step.unit.key} — generating…", flush=True)
                sentence = generator.generate(
                    step.unit, known.units, self._vocabulary(known, priority)
                )
                if sentence is not None:
                    produced.append(sentence)
                    print(f"        {sentence.text}")
                else:
                    print("        (no acceptable sentence after "
                          f"{generator.max_attempts} attempts)")
            known.learn(step.unit)

        if produced:
            app.corpus_store.save(
                app.corpus_store.load(GENERATED) + produced, build=GENERATED
            )
        print(f"\n{gaps} gaps · {len(produced)} generated · "
              f"{generator.attempts} model calls")

    @staticmethod
    def _has_readable_example(examples, unit, known) -> bool:
        """A readable example leaves nothing unknown except the target itself."""
        return any(
            not (s.units - known - {unit})
            for s in examples.examples(unit, known, limit=3)
        )

    @staticmethod
    def _vocabulary(known, priority) -> list[str]:
        words = [u for u in known if not u.is_pattern]
        words.sort(key=priority.of, reverse=True)
        return [u.key for u in words[:VOCABULARY_SAMPLE]]
