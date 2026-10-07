# Workspace design refinement — 2026-10-07

Branch: `codex/learning-experience-redesign`.

This pass keeps the existing Apple-inspired palette and learning behavior,
and brings the application's everyday pages into one consistent workspace.
No feature was removed.

## Changes

- Shared page headings, readable type, calmer spacing, consistent forms,
  buttons, tables, cards and empty/completion states.
- Independently scrolling desktop navigation, expandable collection/journey
  groups, and a visible current destination even on autofocus search pages.
  The mobile menu still exposes every destination.
- Account settings now have section anchors and separate panels. Existing
  password, invitation, visibility and restoration actions remain intact.
- Listening puts the video and answer controls beside each other on desktop
  and stacks them on phones.
- Word collections use cards; dictionary lookup offers example searches.
- Anki exports use two descriptive cards. Previews highlight the deletion
  produced by the existing export function; exported files are unchanged.
- Practice preferences, library imports and technical planning explanations
  use disclosures to keep the primary task readable.
- Video, focused study, contextual watching, sentence editing and word detail
  have correct navigation context.
- Sign-in, invited sign-up and Google sign-up inherit consistent form styling.
- Reels keeps its separate full-screen player and gesture/controller behavior.

## Visual audit

Inspected all 18 primary destinations at desktop size and at 390 × 844:
Learn, Review, Listening, Writing, Vocabulary check, Reels, Video library,
Channels, Saved sentences, Dictionary, Word lists, Anki cards, Your atlas,
Learning path, Watch plan, Next milestones, Learning gaps and Settings.

Also inspected real video, focused study, contextual watching, word detail and
sentence editor routes at both sizes. No document-level horizontal overflow
was observed. Checked the expanded mobile menu and desktop navigation.

Authentication form variants were inspected using local render fixtures without
creating accounts or issuing invitations. The real invitation-required page
was also inspected. The audit did not submit learning decisions, invitations,
password changes or removal actions. Visiting media can record normal listening
encounters through the existing application behavior.

Cold corpus-derived pages occasionally exceeded browser navigation timeouts;
their completed pages were inspected after they finished. This design pass
does not claim to address those backend cold-start delays.

## Verification

- Python: `test_design`, `test_web`, `test_readers`, `test_google`,
  `test_journey`, `test_quiz`: **342 passed, 59 subtests passed** using an
  isolated local PostgreSQL instance.
- JavaScript: `reels-controller.test.cjs`, `hearing-progress.test.cjs`:
  **7 passed**.
- `compileall`, JavaScript syntax check and `git diff --check`: passed.

## Simplification candidates awaiting user approval

1. Move the separate Channels human/synthetic assessment screen into advanced
   library management.
2. Reduce or consolidate the six technical Watch plan choices.
3. Combine Next milestones and Learning gaps into one progress view.

All three remain available until the user chooses a removal or consolidation.
