# Personal video cover

Open **Video cover** in the collection navigation, or **Build a video cover**
from Word lists. Search updates while typing (160 ms debounce), using the
existing corpus vocabulary and a cached trigram posting index. Select results,
name the collection, then choose **Save list & find videos**. Draft selections
survive search changes. Saved collections reopen through the page's `name`
parameter; the generated video set is also kept in the reader's existing
`VideoCoverStore` under `SOURCE:minimum-count`.

## Coverage contract

- One i+1 sentence per unknown selected unit is sufficient: subtract the
  reader's current known units from the complete sentence unit set, and the
  remainder must be exactly that target.
- Knowledge stays frozen during solving. Selected targets never unlock one
  another; words outside the collection still count as unknown.
- Existing strict alias resolution folds duplicate word representations;
  no derived-compound knowledge or minimum video-length rule is added.
- Only timed, teachable, same-language corpus sentences surviving the reader's
  existing corrections, hidden sentences and removed videos are eligible.
- The objective minimizes **number of videos**, then total duration. The CLI
  cover command continues to minimize minutes with its original defaults.
- Already-known and unreachable targets appear separately. When any target is
  unreachable, the result explicitly describes a cover of the coverable words.
- Each selected video includes a witness sentence and a link to its timestamp.
  Timestamp detail links avoid loading the full feed ranking.
- Solver time is bounded at 20 seconds. A feasible incumbent is independently
  audited and displayed as unproven if optimality was not established.

Up to 100 entries can be selected per request. New drafts cannot silently
overwrite another saved collection: open the existing collection to edit it.
Words absent from the current vocabulary and malformed inputs are rejected.
Lists and covers use the existing per-reader schemas and authenticated routes.

## Performance and proof

Cover building reads only sentences containing the selected targets (including
their raw aliases). Both the sentence and unit query are narrowed; every unit
within those sentences is retained, preventing a false i+1 claim. Missing
duration metadata uses the final relevant caption as an explicitly labeled
lower-bound estimate for duration tie-breaking, without excluding the video.

Live search indexes are refreshed when the corpus vintage changes and built
under a per-viewer lock. Short queries select only the top results instead of
sorting/materializing Unit objects for every match. On the local 80,921-unit
subtitle vocabulary, measured warm queries ranged from 22–126 ms for the
sample queries `a`, `an`, `annehmen`, `shriftlich`, `mutig`; cold index creation
and network/UI latency are additional.

Validation: 285 Python tests and 26 subtests passed across minimum-cover,
legacy-cover, word-list, design, web and reels-cache suites; 11 JavaScript tests
passed across cover-builder, reels-controller and hearing-progress suites.
The new PostgreSQL integration test proves multi-target reading preserves
unselected unknowns. Additional tests prove minimum-count priority, frozen
knowledge, reader isolation, saved witnesses, stale-search response rejection,
duplicate selection, failure recovery and timestamp navigation.

Inspected actual desktop and 390 × 844 mobile search/selection/results, saved
and reopened the example collection **Konuşma keşifleri**, and exercised its
minimum cover. Already-known and unreachable words were correctly separated.
