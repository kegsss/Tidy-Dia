from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from dia_organizer import paths


def _load_json(p: Path) -> Optional[dict]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def resolve_from_files(local_state: Path, storable: Path) -> dict[str, str]:
    """Return mapping window_id -> profile display name."""
    ls = _load_json(local_state) or {}
    sp = _load_json(storable) or {}
    info = ((ls.get("profile") or {}).get("info_cache")) or {}
    id_to_name = {pid: meta.get("name", pid) for pid, meta in info.items()}
    out: dict[str, str] = {}
    for c in sp.get("containers", []):
        cid = c.get("id") or {}
        pid = cid.get("profileID")
        win = ((cid.get("container") or {}).get("window") or {}).get("_0")
        if pid and win:
            out[win] = id_to_name.get(pid, pid)
    return out


def resolve_live() -> dict[str, str]:
    return resolve_from_files(paths.dia_local_state(), paths.dia_storable_profiles())
