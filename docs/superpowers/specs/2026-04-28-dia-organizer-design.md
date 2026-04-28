# Dia Organizer — Design Spec

**Date:** 2026-04-28
**Owner:** Keagan McMahon
**Status:** Approved (brainstorm), ready for implementation plan

## Problem

The Dia browser (macOS, Chromium-based) is used across multiple profiles ("Keagan", "Together User", "Demo Together User", "test"). Tab sprawl accumulates over the day as new tabs are opened faster than they are closed; forgotten tabs consume substantial RAM on a MacBook Air M3 and degrade performance. Manual cleanup loses important context. Need automated triage that closes obvious junk, surfaces the ambiguous middle for review, and never silently loses anything that mattered.

## Goals

1. Reduce live tab count per Dia profile without losing tabs the user cared about.
2. Provide a rich, searchable archive of every closed tab with enough context to recall what it was for.
3. Respect profile-specific behavior (work profile is more cautious than personal/test profiles).
4. Be reversible: undo recent closes, snapshot full live state, roll back history.
5. Run unattended on a schedule.

## Non-goals

- Cross-browser support. Dia only.
- Sync to other devices. Single-Mac local utility.
- Public packaging. Personal tool.
- Modifying Dia internals or installing a Dia extension. Use only public OS-level integrations.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  launchd (every 30 min)  →  dia-organizer scan          │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  Scanner (osascript bridge)          │
        │  - resolve profiles from Dia files   │
        │  - enumerate windows / tabs          │
        │  - JS-extract page context per tab   │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │  Classifier                          │
        │  - PROTECT / AUTO-CLOSE / TRIAGE     │
        │  - dedup detector                    │
        │  - cluster grouping                  │
        └──────────────────────────────────────┘
                  │                       │
                  ▼                       ▼
        ┌──────────────────┐    ┌────────────────────┐
        │ Archive (SQLite  │    │  Triage queue      │
        │  + FTS5)         │    │  (sqlite table)    │
        └──────────────────┘    └────────────────────┘
                                          │
                                          ▼
                              ┌────────────────────┐
                              │  Local Flask UI    │
                              │  127.0.0.1:7321    │
                              │  Triage / Archive  │
                              │  / History         │
                              └────────────────────┘
```

### Components

- `dia_organizer/scanner.py` — AppleScript bridge, profile resolution, per-tab inventory + page-context extraction.
- `dia_organizer/classifier.py` — rule pipeline + dedup + cluster grouping.
- `dia_organizer/archive.py` — SQLite + FTS5 reads/writes; transactional close-with-archive.
- `dia_organizer/snapshots.py` — snapshot capture, retention, rollback.
- `dia_organizer/server.py` — Flask localhost UI: Triage, Archive search, History.
- `dia_organizer/cli.py` — `scan`, `triage`, `search`, `reopen`, `stats`, `config`, `snapshot`, `snapshots`, `rollback`, `undo`, `install-schedule`, `uninstall-schedule`.
- `~/Library/LaunchAgents/com.keagan.dia-organizer.plist` — scheduling.
- Data dir: `~/.dia-organizer/` containing `db.sqlite`, `config.toml`, `scan.log`, `scan.err`, `scan.lock`.

## Dia integration — verified facts

Verified on this Mac, 2026-04-28:

1. **AppleScript supported.** `/Applications/Dia.app/Contents/Resources/Dia.sdef` exposes:
   - `application.windows` (read).
   - `window` properties: `id`, `name`, `active tab`, `index`, `visible`, etc. Element `tabs`.
   - `tab` properties: `id`, `title`, `URL` (rw), `loading`, `isPinned`, `isFocused`.
   - Commands: `close`, `focus` (`DiaTabFc`), `execute` JS in tab (`CrSuExJa`), `make`.

2. **Profile / window mapping.** Each Dia profile opens as a separate Dia window (confirmed by user). Mapping resolves from on-disk JSON, no user prompt required:
   - `~/Library/Application Support/Dia/User Data/Local State` → `profile.info_cache` maps internal IDs → display names. Current state: `Default → Keagan`, `Profile 1 → Together User`, `Profile 7 → Demo Together User`, `Profile 10 → test`.
   - `~/Library/Application Support/Dia/StorableProfileContainers.json` → each container has `id.profileID` and (when window is open) `id.container.window._0` UUID matching the AppleScript window id.
   - Scanner reads both, builds `window_id → profile_display_name`. Containers without a `window._0` reference profiles whose window isn't currently open; their tabs are not visible to AppleScript and are skipped.

3. **Live state at design time:** 2 windows reported by AppleScript — `3C6D14AB-…` (331 tabs) and `7236B235-…` (78 tabs). Confirms scale: scanner must handle hundreds of tabs efficiently.

## Scanner

### Per-scan flow

```
1. If Dia not running → exit 0.
2. Acquire ~/.dia-organizer/scan.lock (exclusive). Bail if held.
3. Read Local State + StorableProfileContainers.json → build window_id → profile map.
4. osascript: enumerate windows, for each window enumerate tabs.
5. For each tab:
     - Skip if isPinned (still record it as protected, don't extract context).
     - If tab unseen or URL changed: extract_context() via JS exec.
     - Upsert row in `tabs` table (live state).
6. Mark tabs absent this scan as closed_externally.
7. Take pre-scan snapshot if classifier will auto-close ≥1 tab (decided after step 8 in dry-run pass).
8. Run classifier. Apply auto-closes (transactional). Queue triage rows.
9. Release lock. Write log line. Emit notification if triage queue grew and last notification > 24h ago.
```

### `extract_context(tab)` — JS executed in tab

```js
JSON.stringify({
  metaDesc: document.querySelector('meta[name=description]')?.content,
  ogTitle:  document.querySelector('meta[property="og:title"]')?.content,
  ogDesc:   document.querySelector('meta[property="og:description"]')?.content,
  h1:       document.querySelector('h1')?.innerText?.slice(0,200),
  selection: getSelection().toString().slice(0,500),
  scrollPct: Math.round(scrollY/(document.body.scrollHeight-innerHeight)*100) || 0,
  textSample: document.body.innerText.slice(0,800),
  referrer:  document.referrer
})
```

Cost guards:
- Extract only on first sight or URL change.
- Skip extraction for tabs the rules will auto-close on URL alone (junk domain, blank tab).
- Throttle: at most one JS exec per 200 ms.

## Classifier

### Rule pipeline (first match wins)

```
1. PROTECT      → never touch
   - isPinned == true
   - domain in profile.allowlist_domains
   - first_seen < config.protect_recent_days days ago      (default 3)
   - selection text captured (user highlighted = cared)
   EXCEPTION: dedup-close still permitted within PROTECT
   when an exact-URL duplicate exists (older copy closed,
   newest kept) — losing nothing.

2. AUTO-CLOSE   → archive + close, no prompt
   - exact URL duplicate of another live tab in same profile
   - new-tab / about:blank / empty
   - completed-transaction URL pattern (e.g. amazon.com/gp/buy/.../thankyou,
     *.stripe.com/success)
   - search results pages idle > 1 h (google.com/search, bing.com/search, etc.)
   - domain in profile.junk_domains AND idle > 2 h
   - idle > config.auto_close_idle_days days                (default 14)

3. TRIAGE       → queue for review
   - idle > config.triage_threshold_days days               (default 5)
   - profile tab count > config.soft_tab_limit_per_profile  (default 60),
     pick stalest tabs above limit
   - >5 tabs same domain in same window → cluster suggestion

4. KEEP         → leave open
```

### Cluster grouping (in TRIAGE only)

Group queued tabs before presenting:

- Same domain + first_seen within same 2-hour window → "research session".
- Referrer chain (when `document.referrer` was captured) → "follow-up reading".
- Title TF-IDF cosine > 0.4 → "topic cluster".

UI shows clusters as collapsible cards: e.g. *"8 tabs from a Tailwind research session, 3 days idle"* with "Keep all / Close all / Expand".

### Hard safety caps

- Max 20 auto-closes per scan.
- Max 50 closes per day per profile.
- Excess routes to triage with reason `rate-limited`.
- URL whitelist that NEVER auto-closes regardless of rules:
  `^https?://(localhost|127\.|10\.|192\.168\.|172\.)`, `chrome://`, `about:`, `file://`, `dia://`.
- Per-profile `auto_close_disabled = true` skips step 2 entirely (default for `Together User`).

## Archive schema

```sql
CREATE TABLE tabs (
  archive_id     INTEGER PRIMARY KEY,
  dia_tab_id     TEXT,
  profile        TEXT,
  window_id      TEXT,
  title          TEXT,
  url            TEXT,
  domain         TEXT,
  first_seen     INTEGER,
  last_seen      INTEGER,
  last_focused   INTEGER,
  closed_at      INTEGER,
  close_reason   TEXT,             -- auto:dup | auto:junk | auto:idle | auto:txn-done
                                   -- | auto:search-stale | triage:close | manual | external
  cluster_id     INTEGER,
  meta_desc      TEXT,
  og_title       TEXT,
  og_desc        TEXT,
  h1             TEXT,
  selection      TEXT,
  scroll_pct     INTEGER,
  text_sample    TEXT,
  referrer       TEXT,
  notes          TEXT,
  is_live        INTEGER NOT NULL DEFAULT 1   -- 0 once closed
);

CREATE TABLE clusters (
  cluster_id     INTEGER PRIMARY KEY,
  label          TEXT,
  profile        TEXT,
  created_at     INTEGER,
  reason         TEXT              -- domain | time-window | topic
);

CREATE VIRTUAL TABLE tabs_fts USING fts5(
  title, url, meta_desc, og_title, og_desc, h1, selection, text_sample, notes,
  content='tabs', content_rowid='archive_id'
);

CREATE TABLE triage_queue (
  archive_id     INTEGER PRIMARY KEY REFERENCES tabs,
  queued_at      INTEGER,
  resolution     TEXT,             -- NULL | keep | close | snooze
  snooze_until   INTEGER
);

CREATE TABLE snapshots (
  snapshot_id    INTEGER PRIMARY KEY,
  taken_at       INTEGER,
  label          TEXT,
  trigger        TEXT,             -- hourly | pre-scan | manual | nightly
  profile_count  INTEGER,
  tab_count      INTEGER,
  retention      TEXT              -- hourly | daily | weekly | manual
);

CREATE TABLE snapshot_tabs (
  snapshot_id    INTEGER REFERENCES snapshots,
  profile        TEXT,
  window_id      TEXT,
  dia_tab_id     TEXT,
  position       INTEGER,
  pinned         INTEGER,
  title          TEXT,
  url            TEXT,
  PRIMARY KEY (snapshot_id, profile, dia_tab_id)
);

CREATE TABLE config_window_profiles (
  window_id      TEXT PRIMARY KEY,
  profile        TEXT,
  bound_at       INTEGER
);                                  -- optional manual override; auto-resolution
                                    -- from Dia files is primary
```

## Snapshots & rollback

### Triggers

- Auto hourly on the hour (lightweight: URL + title only, no JS exec).
- Auto immediately before any scan that will auto-close ≥1 tab (`pre-scan`).
- Auto nightly 02:00 (`nightly`, retained 90 days).
- Manual: `dia-organizer snapshot --label "before refactor research"`.

### Retention

- Hourly: last 24.
- Daily: last 14.
- Weekly (Sunday): last 12.
- Manual: kept until user deletes.

### Rollback semantics

- **Default (additive):** reopen any tabs in the snapshot not currently open, in their original profile's window, in original order. Never closes anything live. Safe.
- **`--replace`:** make live state match snapshot exactly — closes tabs not in snapshot. Auto-takes a fresh `pre-rollback` snapshot first so the destructive op is itself reversible.
- **`--dry-run`:** prints diff: would reopen N, would close M.

### Storage estimate

~500 tabs × 200 bytes × ~50 retained snapshots ≈ 5 MB. Negligible.

## Triage UI (Flask, 127.0.0.1:7321)

Single page, three panels (tabbed): **Triage** / **Archive** / **History**.

### Triage panel

- Cluster cards first, then loose tabs.
- Cluster card: label, profile badge, tab count, age, sample 3 titles, buttons `[Keep all]` `[Close all]` `[Expand ▾]`.
- Tab row: favicon, title, domain, profile badge, idle time, og:description preview, buttons `[Keep]` `[Close]` `[Snooze ▾]` (1d/3d/7d/14d/custom), `[Notes ✎]`, `[Open]` (focus the live tab in Dia via AppleScript `focus`).

### Archive panel

- FTS5 search box + filters (profile, date range, close_reason).
- Result rows show full context: title, URL, profile, when archived, why closed, meta_desc/h1/selection/scroll-pct preview, your notes.
- Buttons `[Reopen]` (re-creates tab in profile's window via `make new tab`), `[Copy URL]`, `[Delete from archive]`.

### History panel

- Vertical timeline of snapshots, newest first.
- Each row: timestamp, label, trigger, tab count, delta vs current state (+12 / -3).
- Click → preview pane: tabs that would reopen, tabs currently open not in snapshot.
- Buttons `[Restore (additive)]` `[Restore (replace)]` `[Delete]` `[Pin (keep forever)]`. Confirmation modal for `Restore (replace)`.

### Sidebar (always visible)

- Per-profile live tab counts with soft-limit progress bars.
- "Last scan: 12m ago", "Next scan: 18m".
- Buttons `[Run scan now]` `[Pause auto-close]` `[Open config]`.

### Interaction

- Fully clickable; every action is a button.
- Keyboard accelerators are additive: `j/k` move, `x` close, `k` keep, `s` snooze, `/` focus search, `1/2/3` switch panels.
- Bound to `127.0.0.1` only. No auth, no remote access.

## CLI

```
dia-organizer scan [--dry-run]
dia-organizer triage                    # opens UI in default browser
dia-organizer search "<query>"          # FTS5 over archive, top 20
dia-organizer reopen <archive_id>
dia-organizer stats                     # tab counts per profile, archive size, top domains
dia-organizer config                    # opens config.toml in $EDITOR
dia-organizer snapshot [--label TEXT]
dia-organizer snapshots                 # list
dia-organizer snapshot show <id>        # diff vs current
dia-organizer rollback <id> [--profile P] [--dry-run] [--replace]
dia-organizer snapshot delete <id>
dia-organizer undo                      # reopens auto-closes from last 1 hour
dia-organizer install-schedule
dia-organizer uninstall-schedule
```

## Scheduling — launchd

`~/Library/LaunchAgents/com.keagan.dia-organizer.plist`:

```xml
<plist version="1.0"><dict>
  <key>Label</key><string>com.keagan.dia-organizer</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/keaganmcmahon/.dia-organizer/venv/bin/dia-organizer</string>
    <string>scan</string>
  </array>
  <key>StartInterval</key><integer>1800</integer>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>/Users/keaganmcmahon/.dia-organizer/scan.log</string>
  <key>StandardErrorPath</key><string>/Users/keaganmcmahon/.dia-organizer/scan.err</string>
</dict></plist>
```

Scheduled scan runs auto-close rules silently. Triage queue grows but UI is not auto-opened. Optional macOS notification *"N tabs queued for triage"* once per 24 h via `osascript display notification`.

## Safety — non-negotiables

1. **Archive-before-close, atomic.** `BEGIN → INSERT into tabs → COMMIT → osascript close`. If close fails, archive row remains; dedup handles re-encounter on next scan. If archive fails, close does NOT execute.
2. **Page context captured before close.** JS extraction always runs before close, so archive entry is rich even for auto-closed tabs.
3. **Undo window.** All closes within last 60 minutes reversible via `dia-organizer undo`.
4. **Dry-run default for first 7 days.** `safety.dry_run_until = <ISO date 7 days from install>`. Scanner classifies, archives, queues triage, but does NOT close. User reads logs, tunes rules, then flips flag.
5. **Hard caps:** 20 auto-closes/scan, 50 closes/day/profile.
6. **URL whitelist:** never close localhost/private-IP/`chrome://`/`about:`/`file://`/`dia://`.
7. **Together User extra protection:** `auto_close_disabled = true` by default; only dedup + new-tab/empty closes apply.
8. **Lock file:** `~/.dia-organizer/scan.lock` enforces single concurrent scan.
9. **Quit-aware:** if Dia not running, scan exits 0 immediately.
10. **Snapshot before destructive rollback:** `--replace` rollback always takes a `pre-rollback` snapshot first.

## Config

`~/.dia-organizer/config.toml`:

```toml
[general]
scan_interval_minutes = 30
soft_tab_limit_per_profile = 60
triage_threshold_days = 5
auto_close_idle_days = 14
protect_recent_days = 3
max_auto_closes_per_run = 20
max_closes_per_day_per_profile = 50

[safety]
dry_run_until = "2026-05-05"
undo_window_minutes = 60

[ui]
port = 7321
notify_on_triage_queue_growth = true

[snapshots]
hourly_keep = 24
daily_keep = 14
weekly_keep = 12
nightly_keep_days = 90

[profiles."Keagan"]
junk_domains = ["youtube.com", "x.com", "twitter.com", "reddit.com", "instagram.com"]
allowlist_domains = ["github.com", "obsidian.md"]

[profiles."Together User"]
auto_close_disabled = true
junk_domains = []
allowlist_domains = ["togetherplatform.com", "linear.app", "slack.com", "zendesk.com"]
auto_close_idle_days = 21

[profiles."Demo Together User"]
auto_close_idle_days = 7

[profiles."test"]
auto_close_idle_days = 1
```

## Open questions / deferred

- Whether to surface a macOS menu-bar app later (Swift) for one-click triage. Out of scope for v1.
- Whether to ingest browser history (per-profile Chromium History db) to enrich archive context for tabs closed externally before the scanner saw them. Out of scope for v1.
- Cross-Mac sync of archive. Out of scope.

## Success criteria

- Average live tab count per profile drops below `soft_tab_limit` within 2 weeks of leaving dry-run mode.
- Zero reports of "I lost a tab I cared about" — every closed tab recoverable from archive or snapshot.
- Triage interaction averages < 2 minutes/day.
- Scan completes in < 30 s for ~500 live tabs.
