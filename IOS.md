# Running this on a phone

The goal is to use the app on an iPhone, away from the Mac, with the Mac
asleep. Two screens have to work under a thumb while running: Reels, and the
reading page.

Written after three parallel design passes over the codebase. Numbers here
were measured, not estimated.

## What was decided

| | |
|---|---|
| Reach | anywhere, Mac may be off — so the server moves to an always-on host |
| Reels | vertical swipe = previous/next video. No horizontal gesture. |
| Next | vertical swipe = step the example sentences; right = I know this; left = skip |
| Skip | snoozes the word — it comes back after N others, rather than being lost or forgotten on restart |
| Package | installable web app (PWA), not a native shell |

The rule that makes the two screens learnable: **vertical always means
"another one of these", horizontal always decides.**

PWA rather than Swift because the work is in the web page either way. A
WKWebView shell would wrap the same rewritten pages and add Xcode plus $99/yr;
it buys more reliable gestures and guaranteed screen-wake, which are worth
revisiting only if the PWA disappoints in use.

## Where this stands

Everything below the line is built and running. The phases are kept as the
record of *why* each decision went the way it did, not as a to-do list.

| | |
|---|---|
| Phase 0 reachability | done — `serve --host`, mDNS name, no-auth warning |
| Phase 1 hosting | done in code; runs over Tailscale rather than a VPS |
| Phase 2 PWA shell | done — installs, bottom tab bar, 44px targets |
| Phase 3 JS foundation | done — CSS and JS are files, one keydown listener |
| Phase 4 reading page | done — snooze, gestures, `/api/next` |
| Phase 5 reels feed | done — persistent player, `/api/reels` |

Reached over Tailscale, not a rented VPS. The tailnet gives the two things
the plan wanted from hosting — reachable from anywhere, and membership as
authentication — without a public listener or a monthly bill, and the server
stays bound to one interface. What it does not yet give is HTTPS, which needs
*HTTPS Certificates* enabling in the tailnet admin, and which is the only
thing standing between here and a service worker and Wake Lock.

Things fixed along the way that were not in the plan:

- **`/api/transcript` loaded the entire corpus per call** — 154.1s and 572 MB
  to keep 297 cues, fired by JS on every reading-page load. A `video` filter
  and an index: 0.4s, 0.6 MB.
- **Marking a word known took 23.2s on the request thread.** `_rescore`
  reaches `_grouped`, which materialises the corpus. It is queued now; the
  POST answers in 0.2ms.
- **Curated lemma corrections were being ignored** wherever the parser
  invented a lemma rather than failing cleanly — `muss` came back as `mussn`,
  and the line saying it is `müssen` was skipped, 1,773 times.
- **Videos can be ranked by teaching rate**, not only by how easy they are to
  follow. The two orderings share two videos out of fifty.

## Corrections to assumptions worth carrying

Three things the design passes got wrong or found late. They change the
approach, so they are recorded rather than buried.

1. **Reels does *not* rescan the corpus per navigation.** That belief came
   from a stale docstring on `reels()`, since corrected (`32c0999`).
   `_watchable` reads `video_score` while the stamp holds; a warm load is a
   dictionary lookup. Server cost is not the reason to go client-side.
2. **The real reason is the media unlock.** iOS grants playback permission to
   the *iframe's document*. Tear the iframe down and the next `playVideo()`
   is a fresh unprivileged call, so playback dies after card one. A persistent
   player is the only way programmatic playback survives a swipe.
3. **A cross-origin iframe swallows every touch.** Touches landing on the
   YouTube iframe go to its browsing context and never bubble to the parent, so
   a swipe starting on the video is invisible. `pointer-events: none` on the
   reels iframe is mandatory, not an optimisation — and it means building our
   own play/pause and progress bar.

## Phase 0 — reachability  *(done)*

Nothing is testable on the phone until the first item lands.

- **`web/server.py:19`** — `HOST = "127.0.0.1"` is a module constant. Make it
  an argument on `LocalServer.__init__`, add `--host` in `main.py` and thread
  it through `commands/serve.py`. Needed for LAN testing; production uses
  Tailscale and keeps loopback.
- Print the mDNS `<hostname>.local` address, not the LAN IP. In standalone
  mode there is no address bar — a DHCP lease change bricks an installed app
  with no way to recover but reinstalling.
- **`_rescore` on the POST path** (`web/handlers.py:634` → `1116-1142`). After
  any visit to `/reels`, the next "I know this" materialises the whole corpus
  via `_grouped`, on the request thread, *not* under `self._scoring` — that
  lock covers `_watchable` only. Two quick taps run two concurrent corpus
  loads. Minimum: take the lock inside `_rescore`. Better: move it to a
  queue drained by one daemon worker.
- Keep `server.py:7-9`'s no-auth warning honest: print it when the host is
  not loopback.

## Phase 1 — hosting  *(done, via Tailscale)*

**Tailscale in front of a 4 GB VPS.**

Tailscale answers two requirements at once: `tailscale cert` gives a real
Let's Encrypt certificate on `<host>.<tailnet>.ts.net`, which is the secure
context a service worker and Wake Lock need; and tailnet membership *is* the
authentication for an app that has none. `tailscale serve --bg https /
http://127.0.0.1:8765` terminates TLS in the daemon and proxies to loopback,
so production never binds publicly.

Cloudflare Tunnel gives HTTPS but no auth, and puts a public DNS name in front
of unauthenticated POST routes — one of which writes to the shared Postgres.

4 GB rather than 1 GB because `/blocked`, `/fix`, `/unit/…` and `/watch` still
materialise 200k sentences and 1.2M units; the code's own comment budgets "a
gigabyte and a minute".

**Escape hatch worth taking if it applies:** if the Mac is a desktop,
`sudo pmset -a sleep 0 disablesleep 1` plus Tailscale on the Mac makes this
entire phase disappear. Postgres, spaCy, the caches and the user state are
already co-located there. Everything below is the cost of *not* doing that.

### Making the caches portable

- **`config.py:42-44`** — `os.environ["DB_NAME"]` raises `KeyError` with no
  `.env`, so `Application()` cannot even construct. Use `.get(..., "")` and
  guard `db/connection.py:28-31,69-71` with a clear refusal.
- **`web/handlers.py:1244`** — `/subtitles` calls `_minutes()` unconditionally,
  the one hard Postgres hit on a warm page, and it is redundant: `video_score`
  already stores title and minutes, which is how `/reels` renders them without
  Postgres. Delete it and render from the row.
- **`fingerprint.py:38`** — `analyser_fingerprint()` hashes the *installed
  versions* of `spacy`, `de_core_news_md`, `de_core_news_sm`. A host without
  them computes a different digest, every stamp mismatches, and every page
  falls onto a full corpus walk. Split into a rules hash and a separate
  `packages_fingerprint()` recorded alongside — a spaCy upgrade on the Mac
  should still say "rebuild", but a *different machine* should not look stale.
  Five call sites. (`de_core_news_sm` is loaded by nothing and exists only to
  be hashed; consider dropping it.)
- **`vocab/cache.py:49-66`** — `resolved.json` stamps the **absolute path** plus
  mtime and size, so it cannot survive a checkout elsewhere: `git clone` writes
  identical bytes with fresh mtimes under a different root. Hash contents
  instead. Without this the host resolves the vocabulary from scratch on first
  render and needs Postgres and spaCy to do it.

### Shipping and syncing

The host becomes the single source of truth. This avoids two-way merge, which
would be genuinely hazardous here: nothing records deletes (every removal is a
hard `DELETE` with no tombstone) and every timestamp is timezone-naive, so
"un-marked on the phone" is indistinguishable from "not yet synced".

- Snapshot with `VACUUM INTO`, never rsync a live WAL database. Remove stale
  `-wal`/`-shm` sidecars before swapping the file, and stop the service first.
- Exclude `data/tatoeba.sqlite3` (89 MB, referenced by no code).
- Code and the five `fingerprint.SOURCES` files travel by git — which is also
  how the ~940 known units in `known_words.txt` and `function_words.txt` get
  there. **A host on a different commit runs a different vocabulary with no
  error.** Pin the deploy to a tag and assert `git rev-parse HEAD`.
- Pull `known_units`, `hidden_sentences` and overrides back before each
  rebuild, `INSERT OR IGNORE`. Additive-only is correct: keys are `(kind,key)`
  or sentence text, and unmarking is not something the UI does.
- **Set `TZ` on the host before its first write.** A UTC host writing
  `known_units.marked` and `cards.last_review` while the Mac writes local time
  makes every SRS due date silently wrong.

Rebuilds stay on the Mac — they need Postgres, spaCy and YouTube.

## Phase 2 — the PWA shell  *(done)*

`web/render.py`, `layout()` at 244-261.

- Viewport gains `viewport-fit=cover`. Do **not** add `user-scalable=no`.
- Add `apple-mobile-web-app-capable`, `apple-mobile-web-app-title`,
  `apple-mobile-web-app-status-bar-style: default`, two `theme-color` metas
  matching `--paper`, and links to the manifest and apple-touch-icon.
- **Drop the Google Fonts link** (`render.py:18-20,255-256`). It is a
  render-blocking third-party request; on a phone with no route to the
  internet it stalls with invisible text. iOS ships Charter and Georgia,
  already in the `--serif` chain.
- **Tap targets.** `button` → `min-height:44px`, `font-size:16px`,
  `touch-action:manipulation`. For `.tools button` (~26px today) and
  `.stepper button` (~30px) keep the small visual box and expand only the hit
  area with a `::after { inset:-11px -8px }`.
- **`input[type=text]` → `font-size:16px`.** Below 16px iOS zooms the viewport
  on focus and never zooms back.
- Add the missing `.link` base rule and `.link.off` — the reels pager renders
  unstyled today.
- Safe-area insets on the masthead and `main`; `overscroll-behavior-y: contain`
  to kill pull-to-refresh; `100dvh` rather than `100vh`.
- Move the top nav to a **bottom tab bar** under `@media (max-width:620px)` —
  the masthead is out of thumb reach one-handed.
- **`web/server.py:106-127`** — add a `/static/` branch and `/manifest.webmanifest`
  before the `_missing` fallback, rejecting any path that resolves outside the
  static root. `/favicon.ico` and `/apple-touch-icon.png` currently 404 *as
  HTML*.
- Icon: opaque PNG with margin baked in. iOS ignores `purpose:maskable`,
  applies its own squircle with zero padding, and composites transparency onto
  black.

**No service worker yet.** `http://<host>.local` is not a secure context, so
registration silently fails. Add-to-Home-Screen and `display:standalone` work
over plain HTTP regardless. Once Tailscale's certificate is in place the
secure context exists and a service worker becomes possible.

## Phase 3 — JS foundation  *(done)*

**Move CSS and JS into real files** served by the Phase 2 static route:
`web/static/app.css` (the whole of `STYLE`) and `web/static/app.js`. The
gesture engine plus two controllers is 350-450 lines, and f-strings are hostile
to it — every JS `{` needs doubling, which is why `merged_script()` is already
a plain string. External files also cache across navigations.

Per-page data crosses as JSON in a `<script type="application/json">` block,
never interpolated into JS.

**Delete all three script emitters:** `_reel_keys` (`handlers.py:1004-1020`),
`_DECK_SCRIPT` (`1439-1467`), and the keydown block inside `merged_script`
(`watch.py:243-249`). This kills a live bug for free: `next_up` emits both
`_DECK_SCRIPT` and `merged_script`, each registering its own `keydown` with its
own `showing`, so arrow keys advance the deck twice with a desynced counter.
One listener for the whole app makes it impossible.

**Keyboard mapping is a behaviour change worth flagging.** ArrowRight steps the
deck today; under "horizontal decides" it becomes *mark known* — the same key,
now a write. Muscle memory will mark words by accident. Up/down (and `j`/`k`)
step sentences; left/right decide. The hint text at `handlers.py:402` says only
"arrow keys" and must name both axes.

**Gesture engine:** Pointer Events; lock the axis after ~10px of travel; commit
at >22% of the surface or >0.35 px/ms. Ignore `pointerdown` with
`clientX < 24` — iOS reserves the left edge for interactive back even in
standalone, so "skip" would randomly navigate backwards. Scope
`touch-action:none` to the gesture surface only, never the document; any
`preventDefault` backstop on `window`/`document` must register `{passive:false}`
or it is a silent no-op.

## Phase 4 — the reading page  *(done)*

**Snooze** (new, `vocab/snooze_store.py`, modelled on `known_store.py`):

- Its own table, not the `cards` table. `due_date` answers "when should I be
  tested"; snooze answers "don't offer this yet". They coincide today only
  because all 49,642 cards sit at `due_date <= now` and none has ever been
  reviewed — the first real review would make every reviewed word vanish from
  Next.
- Counted in **words offered**, not wall-clock: timestamps here are
  timezone-naive, the app is used in bursts, and a 1-hour snooze fires
  mid-session while a 1-day snooze never returns that day. A monotonic tick
  bumped once per decision, `wake_tick = tick + N`, default **N = 20**.
- Escalate on repeat with a hard cap — `min(N * 2**(times-1), 200)`. The cap is
  load-bearing: uncapped doubling puts an eight-times-skipped word 2,560 words
  away, which is the "lost forever" outcome that was rejected.
- Replaces `_passed` (`handlers.py:79`) at all five sites, rather than sitting
  beside it. Filters `_planned` and `_walked`; ledger pages are not filtered.
- **Empty-pool guard:** if the filter leaves no step, re-run ignoring it rather
  than rendering "Nothing left that is i+1" — that headline would be a lie when
  the only thing in the way is your own skips.
- Undo: snooze is a row, so undo is a delete. A one-line bar after a swipe plus
  a collapsed list of what is set aside.

**Gestures.** Vertical steps the deck — all 24 slides are already in the DOM as
`.slide` divs, so this costs zero server work. Horizontal posts a decision and
swaps in the next word. One prefetch serves both directions: `_planned` skips on
`unit in known or snoozed`, so "next step excluding X" is the same page whether
X was known or skipped.

Decisions go out with `fetch(..., {redirect:'manual', keepalive:true})` so the
server never renders a page the client discards. Keep the `<form>` markup and
intercept `submit`, so a JS-less browser still works.

New `/api/next` endpoint returning the fragments `_deck`, `_actions` and
`_progress` already produce, refactored so `next_up` and the JSON path share
them. `_send_json` must set `Cache-Control: no-store` or the phone serves a
stale rank window straight after a mark.

## Phase 5 — Reels as a feed  *(done)*

- **`pointer-events: none` on the iframe**, `controls=0`, and build our own tap
  and progress bar off the 250ms tick that already exists. Without this no
  swipe starting on the video is ever seen. Only reels needs it; `/` and
  `/watch` keep their own controls.
- **`playsinline=1`** on both `player()` (`watch.py:31-38`) and `stage()`
  (`257-263`), and `allow` must gain `autoplay`. Keep the hand-written iframe:
  the IFrame API does not set `allow` on an iframe it constructs, and `allow`
  must be present at load. `allow=autoplay` is load-bearing, not polish — with
  input handled in the parent, every `playVideo()` is programmatic.
- **One persistent `YT.Player`**, never destroyed. See correction (2).
- **Address the feed by video id, never by rank.** `reels()` is indexed by `i`,
  and `_rescore` re-sorts the ranking, so `i` stops meaning the same video the
  moment a word is marked. Keep a per-source seen-list server-side and return
  the highest-ranked unseen row; backwards reads the client's own history.
  Reordering then only affects what comes next, and nothing behind the user
  moves. A pull-down at the top is the explicit "re-rank now".
- After marking from the panel, don't re-fetch — grey the row and bump
  comprehension optimistically by `count / lines`, both already in the row.
- Full-bleed CSS keyed off a `body_class` on `layout()`. The video stays 16:9
  letterboxed on black: a YouTube embed cannot be honestly cropped to 9:16.

## Verification

- `pytest -q` stays green at 113 throughout; each phase is independently
  shippable.
- Safari Web Inspector over USB against the `.local` host. In order: no
  horizontal overflow at 320px; every target ≥44px; input focus does not zoom;
  no rubber-band; a swipe starting dead-centre on the video is seen; **playback
  survives three consecutive swipes** (the unlock test); reinstall from the
  Home Screen after `_rescore` has run.
- On the host: assert `analyser_fingerprint()` matches the shipped
  `roadmap_meta`, `build_meta` and `video_score_meta` stamps, and refuse to
  start otherwise. Warm the score cache before first use or the phone's first
  `/reels` pays the full rescore.

## Risks

1. **Fingerprint drift.** Any edit to `phrase_finder.py`, `analyzer.py`,
   `filter.py`, `final_result.txt` or `lemma_overrides.txt` changes the rules
   hash on the next `git pull` and silently drops the host onto a corpus walk.
   The start-up assertion above is the mitigation.
2. **RAM cliff survives everything here.** `/blocked`, `/fix`, `/unit/…`,
   `/watch` still materialise the corpus. Either accept ~60s plus swap, or drop
   them from the phone nav and keep them Mac-only.
3. **Accidental swipe while scrolling.** The dx/dy ratio and multitouch abort
   are the whole defence; get them wrong and every scroll snoozes a word.
4. **Left-edge swipes are stolen by iOS back**, including in standalone.
5. **No service worker until HTTPS**, so no offline and no push. Video needs
   the network regardless, so offline was never going to cover Reels.
6. **Data leaves the Mac** — subtitle text and your vocabulary sit on rented
   disk.
7. **Roadmap head exhaustion.** `_planned` falls to the slow `_walked` as soon
   as a step has an empty deck; more snoozing pushes the scan further down.
   Rebuild roadmaps periodically, not only when the corpus changes.

## Still open

- **HTTPS**, and with it the service worker and Wake Lock. Needs *HTTPS
  Certificates* switched on at `login.tailscale.com/admin/dns`, then
  `tailscale serve`.
- **A roadmap over videos** rather than words — ordering them so each accounts
  for what the ones before it taught. The word-level walk is the same shape.
- **Packaging.** Everything here assumes a PWA. A WKWebView shell wraps the
  same pages and changes nothing in phases 2-5; it buys more reliable gestures
  and guaranteed screen-wake for the cost of Xcode and a developer account.
  Worth deciding only after the PWA has been used on a run.
- Three invented-lemma rows the verb guard deliberately refuses, and 984
  assumed-known words that `quiz` has never checked.
