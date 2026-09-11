"""`lookup` — the words worth searching for, as links you can click.

The hunt asks YouTube's relevance ranking for `<word> deutsch`, which reads
no captions and so cannot know whether a video says the word at all. A
caption search does know. YouGlish is one, and its robots.txt disallows the
endpoints an automated search would have to call, so this does the half a
program may do: works out which words are worth looking for, and hands over
the addresses.

Paste whatever you find back into `add-videos`, which takes URLs.
"""
from __future__ import annotations

from urllib.parse import quote

from roadmap import CorpusIndex
from roadmap.store import RoadmapStore, current_stamp

WHERE = "https://de.youglish.com/pronounce/{word}/german"


class LookupCommand:
    def run(self, app, limit: int = 25, source: tuple[str, ...] = (),
            absent_only: bool = True) -> None:
        from commands.hunt_videos import (                   # noqa: PLC0415
            HuntVideosCommand, _search_terms)

        settings = app.settings
        builds = tuple(source) or ("subtitle",)
        label = "+".join(builds)
        sentences = app.corpus(*builds, list_only=True)
        if not sentences:
            raise SystemExit(f"nothing cached for {label}")
        HuntVideosCommand._corpus = (label, sentences)
        stuck = HuntVideosCommand._stranded(app, label, app.known_set(), True)

        counts = app.corpus_store.unit_counts(*builds)
        rows = [(u, n) for u, n in stuck
                if not (absent_only and counts.get((u.kind, u.key), 0))]
        if not rows:
            print("nothing stranded that video could help with.")
            return

        print(f"{len(rows):,} words worth looking for"
              f"{' — never said here at all' if absent_only else ''}."
              f" Showing {min(limit, len(rows))}.\n")
        for unit, _ in rows[:limit]:
            # The search word, not the entry: `der Beamte, die Beamte` is
            # looked up as `Beamte`, the way the hunt derives its terms. One
            # heading with every spelling under it, since an entry naming
            # alternatives is one word to find, not two.
            print(f"  {unit.key}")
            for term in dict.fromkeys(_search_terms(unit)):
                print(f"      {WHERE.format(word=quote(term))}")
        print("\nPaste what you find into:  python main.py add-videos -")
