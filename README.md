# Dia Organizer

Tame Dia browser tab sprawl across multiple profiles on macOS.

## Install

```bash
git clone https://github.com/kegsss/Tidy-Dia.git
cd Tidy-Dia
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Quick start

```bash
# First scan in dry-run (default for 7 days after install)
.venv/bin/dia-organizer scan

# Open the triage UI
.venv/bin/dia-organizer serve            # http://127.0.0.1:7321

# Search the archive
.venv/bin/dia-organizer search "tailwind"

# Take a manual snapshot
.venv/bin/dia-organizer snapshot --label "before research"

# Roll back (additive)
.venv/bin/dia-organizer rollback 5 --dry-run

# Install background schedule (every 30 min)
.venv/bin/dia-organizer install-schedule
```

## Configuration

`~/.dia-organizer/config.toml` — see `docs/superpowers/specs/2026-04-28-dia-organizer-design.md` for the full schema.

## Dia Tab-Group Bridge (optional)

A small Manifest V3 extension lets `dia-organizer` create native Dia tab groups
for your triage / auto-close candidates. Lives in `extension/tidy-dia-bridge/`.

**Install (per Dia profile):**

1. Make sure `dia-organizer serve` is running (`http://127.0.0.1:7321/`).
2. Open `dia://extensions/` in the target Dia profile.
3. Toggle **Developer mode** ON (top-right).
4. Click **Load unpacked** → pick the folder `extension/tidy-dia-bridge`.
5. The extension service worker polls `127.0.0.1:7321/ext/poll` every 5 s.

**Usage:**

```bash
.venv/bin/dia-organizer corral-triage --idle-days 10
.venv/bin/dia-organizer corral-autoclose --idle-days 10 --color red
```

Each command POSTs the candidate URL list to the running server. The extension
picks it up on its next poll and uses `chrome.tabGroups` to create collapsed
groups in whichever Dia windows contain those URLs.

Notes:

- The extension only groups tabs already open in the current Dia profile's
  windows. URLs not currently open are skipped.
- Tab groups are session-only in current Dia (`dia://saved-tab-groups-unsupported`).
  Closing/reopening the window discards the grouping.
- Install the extension separately into each Dia profile you want grouping in.

## Safety

- Dry-run default for 7 days after install.
- Every closed tab archived with full page context before close.
- 60-minute undo window on auto-closes.
- Hard caps: 20 auto-closes/scan, 50 closes/day/profile.
- Per-profile rules (work profile defaults to no auto-close).
- Snapshots before destructive rollback.
