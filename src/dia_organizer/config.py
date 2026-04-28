from __future__ import annotations
import datetime as dt
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dia_organizer import paths


@dataclass
class ProfileConfig:
    name: str
    auto_close_disabled: bool = False
    junk_domains: list[str] = field(default_factory=list)
    allowlist_domains: list[str] = field(default_factory=list)
    auto_close_idle_days: int = 14


@dataclass
class Config:
    scan_interval_minutes: int = 30
    soft_tab_limit_per_profile: int = 60
    triage_threshold_days: int = 5
    auto_close_idle_days: int = 14
    protect_recent_days: int = 3
    max_auto_closes_per_run: int = 20
    max_closes_per_day_per_profile: int = 50
    dry_run_until: Optional[dt.date] = None
    undo_window_minutes: int = 60
    ui_port: int = 7321
    notify_on_triage_queue_growth: bool = True
    hourly_keep: int = 24
    daily_keep: int = 14
    weekly_keep: int = 12
    nightly_keep_days: int = 90
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)

    def dry_run_active(self) -> bool:
        return self.dry_run_until is not None and self.dry_run_until > dt.date.today()

    def profile(self, name: str) -> ProfileConfig:
        if name in self.profiles:
            return self.profiles[name]
        return ProfileConfig(name=name, auto_close_idle_days=self.auto_close_idle_days)


def load(path: Optional[Path] = None) -> Config:
    cfg = Config()
    p = path or paths.config_path()
    if not p.exists():
        return cfg
    data = tomllib.loads(p.read_text())
    g = data.get("general", {})
    for key, val in g.items():
        if hasattr(cfg, key):
            setattr(cfg, key, val)
    s = data.get("safety", {})
    if "dry_run_until" in s:
        v = s["dry_run_until"]
        cfg.dry_run_until = v if isinstance(v, dt.date) else dt.date.fromisoformat(v)
    if "undo_window_minutes" in s:
        cfg.undo_window_minutes = s["undo_window_minutes"]
    ui = data.get("ui", {})
    cfg.ui_port = ui.get("port", cfg.ui_port)
    cfg.notify_on_triage_queue_growth = ui.get(
        "notify_on_triage_queue_growth", cfg.notify_on_triage_queue_growth
    )
    snap = data.get("snapshots", {})
    for key in ("hourly_keep", "daily_keep", "weekly_keep", "nightly_keep_days"):
        if key in snap:
            setattr(cfg, key, snap[key])
    for name, pdata in data.get("profiles", {}).items():
        cfg.profiles[name] = ProfileConfig(
            name=name,
            auto_close_disabled=pdata.get("auto_close_disabled", False),
            junk_domains=list(pdata.get("junk_domains", [])),
            allowlist_domains=list(pdata.get("allowlist_domains", [])),
            auto_close_idle_days=pdata.get("auto_close_idle_days", cfg.auto_close_idle_days),
        )
    return cfg
