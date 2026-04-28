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


def apply_overrides(base: dict[str, str], conn) -> dict[str, str]:
    """Layer manual window→profile overrides from config_window_profiles."""
    out = dict(base)
    for row in conn.execute("SELECT window_id, profile FROM config_window_profiles"):
        out[row["window_id"]] = row["profile"]
    return out


def resolve_for_scan(conn) -> dict[str, str]:
    return apply_overrides(resolve_live(), conn)


def bind_window(conn, window_id: str, profile: str, now: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO config_window_profiles(window_id, profile, bound_at) "
        "VALUES (?,?,?)",
        (window_id, profile, now),
    )
    conn.commit()


def unbind_window(conn, window_id: str) -> None:
    conn.execute("DELETE FROM config_window_profiles WHERE window_id=?", (window_id,))
    conn.commit()
