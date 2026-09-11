"""`out-of-reach` — the goals this corpus cannot teach, written down.

The roadmap walks until nothing is one word away; whatever is left is
stranded. This reports it, and the report is worth having on disk because
what you do about a stranded goal depends entirely on *why* it is stranded,
and the file says which:

  said 0      never in the corpus at all. One video saying it creates the
              first sentence, which is what `hunt --absent-only` chases.
  said 55     here, and never once the only unknown. More video rarely helps
              — the word is not scarce, its company is.

Kept as a file rather than printed because the answer costs a corpus load and
a walk, and because the difference between two runs is the interesting part.

It exists as a command for a duller reason. The first version of
`data/b1_out_of_reach.txt` was written by a script in a scratch directory
that went away with its session. The file stayed, claiming to be current,
while the corpus grew 53,134 sentences underneath it — and when it was
finally re-run it went from 218 entries to 28. A report nothing can
regenerate is a report that quietly starts lying.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from commands.hunt_videos import HuntVideosCommand


class OutOfReachCommand:
    def run(self, app, source: tuple[str, ...] = (), out: str | None = None,
            quality_only: bool = True) -> None:
        settings = app.settings
        builds = list(source) or list(app.corpus_store.builds())
        if not builds:
            raise SystemExit("no cached corpus — run `build-corpus` first")
        destination = Path(out) if out else self._beside(settings.goal_words)

        print(f"loading {'+'.join(builds)}…", flush=True)
        sentences = app.corpus(*builds, list_only=True)
        if not sentences:
            raise SystemExit(f"nothing cached for {'+'.join(builds)}")

        # `_stranded` takes one source name and reads the corpus through its
        # own cache; this is two builds at once. Priming the cache hands it
        # exactly the sentences we mean while leaving the walk — which is the
        # part that must not drift from what `hunt` acts on — untouched.
        label = "+".join(builds)
        HuntVideosCommand._corpus = (label, sentences)
        stuck = HuntVideosCommand._stranded(
            app, label, app.known_set(), quality_only)

        absent = [(u, n) for u, n in stuck if not n]
        crowded = [(u, n) for u, n in stuck if n]
        before = self._count(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(
            self._header(settings, builds, len(sentences), quality_only)
            + [f"{unit.key}\t{said}" for unit, said in stuck]) + "\n",
            encoding="utf-8")

        moved = f"  ({len(stuck) - before:+,} against the last run)" if before else ""
        print(f"\n{destination} — {len(stuck):,} goals out of reach{moved}")
        print(f"  {len(absent):>4} never said here      "
              "— video creates the first sentence (`hunt --absent-only`)")
        print(f"  {len(crowded):>4} said but never alone "
              "— more video rarely helps; these are the hard ones")
        for unit, said in crowded[:8]:
            print(f"         {unit.key:<34} said {said}")

    @staticmethod
    def _beside(goals: Path) -> Path:
        """`data/b1_parsed.txt` -> `data/b1_out_of_reach.txt`.

        Named after the list it is about, because a second goal list would
        otherwise overwrite the first one's report without saying so.
        """
        stem = goals.stem
        for suffix in ("_parsed", "_list", "_words"):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        return goals.with_name(f"{stem}_out_of_reach.txt")

    @staticmethod
    def _count(path: Path) -> int:
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines()
                   if line.strip() and not line.startswith("#"))

    @staticmethod
    def _header(settings, builds: list[str], sentences: int,
                quality_only: bool) -> list[str]:
        """What produced it, so a stale copy can be recognised as one."""
        return [
            "# Goals this corpus cannot teach, most-said first.",
            "# The count is how often the corpus says it — a high count means",
            "# the word is here and always crowded, not that it is missing.",
            "#",
            f"# Regenerated {date.today().isoformat()} from {sentences:,}"
            f" sentences ({'+'.join(builds)}),",
            f"# goals {settings.goal_words}, well-formed only = {quality_only}.",
            "# Rebuild with `python main.py out-of-reach` — do not hand-edit.",
        ]
