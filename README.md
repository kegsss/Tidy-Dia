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

## Safety

- Dry-run default for 7 days after install.
- Every closed tab archived with full page context before close.
- 60-minute undo window on auto-closes.
- Hard caps: 20 auto-closes/scan, 50 closes/day/profile.
- Per-profile rules (work profile defaults to no auto-close).
- Snapshots before destructive rollback.
