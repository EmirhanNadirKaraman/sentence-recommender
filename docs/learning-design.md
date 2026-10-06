# Learning workspace redesign

The app should feel like an inviting place to learn: easy to begin, comfortable
to read, and rewarding to return to. The target is sustained, useful practice.
Longer sessions and better retention are hypotheses to measure with learners,
not outcomes that visual changes alone can promise.

## Research translated into design

- [Duolingo: redesigning the core tabs](https://blog.duolingo.com/core-tabs-redesign/):
  consistent heading placement, typography, spacing, and components make separate
  features feel like one product. Applied through a shared shell, lilac surfaces,
  a vivid purple accent with coral, cyan, and amber supporting colors, reading typography, and reusable cards across every route.
- [Duolingo: the home-screen learning path](https://blog.duolingo.com/new-duolingo-home-screen-design/):
  provide a clear next step and incorporate review into the learning journey.
  The home page prioritizes continuing the next i+1 sentence, with direct routes
  to spaced review, video discovery, and writing. The existing SRS and ranking
  behavior remain the source of truth.
- [Nielsen Norman Group: recognition rather than recall](https://www.nngroup.com/articles/recognition-and-recall/):
  make available actions visible and recognizable. Seventeen destinations now
  belong to four labeled groups: practice, exploration, collection, and journey.
  Mobile has four frequent destinations plus a complete native More disclosure.
- [Nielsen Norman Group: usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/):
  show system status, reduce clutter, preserve user control, and provide recovery.
  Readable-sentence progress uses the actual corpus denominator; no streaks or
  achievements are fabricated. Video cards expose familiarity and list words,
  with all detailed comparisons available in a disclosure. Empty home states
  offer usable next actions instead of terminal commands.

## Implementation

- Shared navigation and context chips preserve the current corpus and word list.
- Reading, review, writing, quiz, saved sentences, vocabulary lists, transcripts,
  video controls, account pages, and empty states use the same visual system.
- The video library shows up to 24 visual cards in the selected ranking; the
  complete catalogue remains available in the comparison disclosure. Search
  keeps the selected word list and matches titles or YouTube URLs as before.
- Small screens use a bottom bar with a scrollable two-column section picker.
  Escape and clicking outside dismiss it; it remains usable without scripting.
- Native progress, labeled navigation, current-page markers, skip-to-content,
  keyboard focus indicators, dark mode, reduced motion, safe-area insets, and
  zoom support remain part of the design.
- Fonts and icons are local/system resources. Video thumbnails load lazily from
  YouTube, matching the provider already used for playback.
- Shared JavaScript loads once, including on account pages. Existing player,
  transcript, word gloss, saving, swiping, and keyboard bindings are preserved.

## Validation and remaining evidence

Automated coverage verifies route validity, shell behavior, selected-list
continuity, script deduplication, progress denominators, safe video titles, and
catalogue destinations. Browser checks use illustrative fixtures for layout and
navigation; they do not certify real learner grading or playback.

The full web suite needs a separate `sentence_recommender_test` database. That
snapshot's database was missing and the configured user could not create it.
Database-backed tests must be rerun once that prerequisite is supplied. The
redesign does not change the SRS, database schema, or scoring algorithms.

Before claiming increased retention, measure time to first practice, completed
review sessions, return visits, and learner-reported comfort; also observe people
using the new grouped navigation on phones. No analytics or tracking was added.
