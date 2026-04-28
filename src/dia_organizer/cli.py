from __future__ import annotations
import shutil
import subprocess
import sys
import time
import click

from dia_organizer import applescript, archive, classifier, config as cfgmod, db, paths as paths_mod, scanner, scheduling, server, snapshots


@click.group()
def main():
    """dia-organizer — tame Dia tab sprawl."""


@main.command()
@click.option("--dry-run", is_flag=True, help="Force dry-run regardless of config")
@click.option("--no-close", is_flag=True, help="Alias for --dry-run (no tabs closed)")
@click.option("-v", "--verbose", is_flag=True, help="List per-tab close/triage candidates")
@click.option("--triage-days", type=int, default=None,
              help="Override config.triage_threshold_days for this scan only")
@click.option("--protect-recent-days", type=int, default=None,
              help="Override config.protect_recent_days for this scan only")
def scan(dry_run: bool, no_close: bool, verbose: bool, triage_days, protect_recent_days):
    cfg = cfgmod.load()
    if dry_run or no_close:
        import datetime as dt
        cfg.dry_run_until = dt.date.today() + dt.timedelta(days=1)
    if triage_days is not None:
        cfg.triage_threshold_days = triage_days
    if protect_recent_days is not None:
        cfg.protect_recent_days = protect_recent_days
    conn = db.open_db()
    res = scanner.run_scan_cli_safe(conn, cfg)
    if cfg.notify_on_triage_queue_growth and res.get("triaged", 0) > 0:
        from dia_organizer import notifications
        notifications.notify("Dia Organizer", f"{res['triaged']} tabs queued for triage")
    click.echo(
        f"status={res.get('status')} dry_run={res.get('dry_run')} "
        f"would_close={res.get('would_close_count', 0)} "
        f"closed={res.get('closed', 0)} triaged={res.get('triaged', 0)} "
        f"rate_limited={res.get('rate_limited', 0)}"
    )
    if res.get("status") == "ok":
        live = list(conn.execute(
            "SELECT profile, COUNT(*) AS n FROM tabs WHERE is_live=1 GROUP BY profile ORDER BY n DESC"
        ))
        for r in live:
            click.echo(f"  {r['profile']}: {r['n']} live tabs")
        if verbose:
            for c in res.get("auto_close_candidates", []):
                click.echo(f"  CLOSE [{c['reason']}] [{c['profile']}] {c['title'][:60]} — {c['url']}")
            for c in res.get("triage_candidates", []):
                click.echo(f"  TRIAGE [{c['reason']}] [{c['profile']}] {c['title'][:60]} — {c['url']}")


@main.command()
@click.argument("query")
def search(query: str):
    conn = db.open_db()
    rows = archive.search(conn, query)
    if not rows:
        click.echo("(no results)")
        return
    for r in rows:
        click.echo(f"[{r['profile']}] {r['title']}")
        click.echo(f"   {r['url']}")
        if r["meta_desc"]:
            click.echo(f"   {r['meta_desc'][:120]}")
        click.echo("")


@main.command()
@click.argument("archive_id", type=int)
def reopen(archive_id: int):
    conn = db.open_db()
    row = archive.reopen_record(conn, archive_id)
    if not row:
        raise click.ClickException(f"archive_id {archive_id} not found")
    new_id = applescript.make_tab(row["window_id"], row["url"])
    click.echo(f"reopened tab {new_id} in window {row['window_id']}")


@main.command()
def undo():
    cfg = cfgmod.load()
    conn = db.open_db()
    rows = archive.closed_within(conn, cfg.undo_window_minutes * 60, int(time.time()))
    if not rows:
        click.echo("nothing to undo")
        return
    for r in rows:
        try:
            applescript.make_tab(r["window_id"], r["url"])
            click.echo(f"reopened: {r['title']}")
        except applescript.AppleScriptError as e:
            click.echo(f"failed: {r['title']} ({e})")


@main.command()
def stats():
    conn = db.open_db()
    rows = list(conn.execute(
        "SELECT profile, COUNT(*) AS n FROM tabs WHERE is_live=1 GROUP BY profile"
    ))
    for r in rows:
        click.echo(f"{r['profile']}: {r['n']} live tabs")


@main.command()
def triage():
    cfg = cfgmod.load()
    import webbrowser
    url = f"http://127.0.0.1:{cfg.ui_port}/"
    click.echo(f"opening {url}")
    webbrowser.open(url)


@main.command(name="snapshot")
@click.option("--label", default="manual")
def snapshot_cmd(label: str):
    conn = db.open_db()
    windows = applescript.list_tabs()
    win_map = profiles_module().apply_overrides(profiles_module().resolve_live(), conn)
    sid = snapshots.take(conn, windows, win_map,
                          label=label, trigger="manual",
                          retention="manual", now=int(time.time()))
    click.echo(f"snapshot {sid} ({len(windows)} windows)")


@main.command(name="snapshots")
def snapshots_cmd():
    conn = db.open_db()
    rows = snapshots.list_all(conn)
    for r in rows:
        click.echo(f"{r['snapshot_id']:>4}  {r['taken_at']}  {r['retention']:<8} "
                   f"tabs={r['tab_count']:<4} {r['label']}")


@main.command()
@click.argument("snapshot_id", type=int)
@click.option("--profile", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--replace", is_flag=True)
def rollback(snapshot_id: int, profile: str | None, dry_run: bool, replace: bool):
    conn = db.open_db()
    windows = applescript.list_tabs()
    win_map = profiles_module().apply_overrides(profiles_module().resolve_live(), conn)
    plan = snapshots.plan_rollback(conn, snapshot_id, windows, win_map,
                                    replace=replace, profile_filter=profile)
    if dry_run:
        click.echo(f"would reopen {len(plan['to_open'])} tabs, "
                   f"would close {len(plan['to_close'])} tabs")
        return
    if replace:
        snapshots.take(conn, windows, win_map,
                        label=f"pre-rollback-of-{snapshot_id}",
                        trigger="pre-rollback", retention="manual",
                        now=int(time.time()))
    for t in plan["to_open"]:
        try:
            applescript.make_tab(t["window_id"], t["url"])
        except applescript.AppleScriptError:
            pass
    for t in plan["to_close"]:
        try:
            applescript.close_tab(t["window_id"], t["dia_tab_id"])
        except applescript.AppleScriptError:
            pass
    click.echo(f"reopened {len(plan['to_open'])}, closed {len(plan['to_close'])}")


def profiles_module():
    from dia_organizer import profiles as _p
    return _p


@main.command()
@click.option("--idle-days", type=int, default=None,
              help="Simulate every tab being idle for N days (overrides actual idle time).")
@click.option("--protect-recent-days", type=int, default=None,
              help="Override config.protect_recent_days for this preview only.")
@click.option("--triage-days", type=int, default=None,
              help="Override config.triage_threshold_days for this preview only.")
@click.option("--limit", type=int, default=200, help="Max rows to print")
def preview(idle_days, protect_recent_days, triage_days, limit):
    """Show what classifier WOULD decide right now with optionally relaxed
    thresholds. NO DB writes, NO closes. Uses tabs already recorded in DB.

    Examples:
      dia-organizer preview --idle-days 10
        \b
        Show what would happen if every live tab were 10 days idle.

      dia-organizer preview --protect-recent-days 0 --triage-days 0
        \b
        Show classifier decisions ignoring the recency floor.
    """
    cfg = cfgmod.load()
    if protect_recent_days is not None:
        cfg.protect_recent_days = protect_recent_days
    if triage_days is not None:
        cfg.triage_threshold_days = triage_days
    conn = db.open_db()
    now = int(time.time())
    rows = [dict(r) for r in conn.execute("SELECT * FROM tabs WHERE is_live=1")]
    if idle_days is not None:
        for r in rows:
            r["last_seen"] = now - idle_days * 86_400
            r["last_focused"] = now - idle_days * 86_400
            # also age first_seen so protect-recent doesn't bypass
            if (now - r["first_seen"]) < idle_days * 86_400:
                r["first_seen"] = now - idle_days * 86_400 - 1
    decisions = [(r, classifier.classify(r, rows, cfg, now)) for r in rows]
    by_action = {"AUTO_CLOSE": [], "TRIAGE": [], "PROTECT": [], "KEEP": []}
    for r, d in decisions:
        by_action[d.action].append((r, d))
    click.echo(f"PROTECT={len(by_action['PROTECT'])} "
               f"AUTO_CLOSE={len(by_action['AUTO_CLOSE'])} "
               f"TRIAGE={len(by_action['TRIAGE'])} "
               f"KEEP={len(by_action['KEEP'])}")
    shown = 0
    for action in ("AUTO_CLOSE", "TRIAGE"):
        for r, d in by_action[action]:
            click.echo(f"  {action} [{d.reason}] [{r['profile']}] "
                       f"{(r['title'] or '')[:60]} — {r['url']}")
            shown += 1
            if shown >= limit:
                click.echo(f"  ... (showing {limit} of "
                           f"{len(by_action['AUTO_CLOSE']) + len(by_action['TRIAGE'])})")
                return


def _post_extension_command(cfg, action: str, urls: list[str], title: str, color: str) -> None:
    """POST a grouping command to the running Flask server's /ext endpoint.
    Only works while `dia-organizer serve` is running."""
    import json
    import urllib.error
    import urllib.request
    body = json.dumps({"action": action, "urls": urls, "title": title, "color": color}).encode()
    url = f"http://127.0.0.1:{cfg.ui_port}/ext/enqueue"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            payload = json.loads(resp.read().decode())
            click.echo(f"queued cmd id={payload.get('id')} ({len(urls)} urls) — extension will pick up within ~5s")
    except urllib.error.URLError as e:
        raise click.ClickException(
            "Could not reach the dia-organizer server. Start it with "
            "`dia-organizer serve` in another terminal first."
        ) from e


def _candidates_from_preview(idle_days: int) -> tuple[list[str], list[str]]:
    """Run classifier with idle_days override, return (autoclose_urls, triage_urls)."""
    from dia_organizer import classifier as _clf
    cfg = cfgmod.load()
    conn = db.open_db()
    now = int(time.time())
    rows = [dict(r) for r in conn.execute("SELECT * FROM tabs WHERE is_live=1")]
    if idle_days > 0:
        for r in rows:
            r["last_seen"] = now - idle_days * 86_400
            r["last_focused"] = now - idle_days * 86_400
            if (now - r["first_seen"]) < idle_days * 86_400:
                r["first_seen"] = now - idle_days * 86_400 - 1
    auto, tri = [], []
    for r in rows:
        d = _clf.classify(r, rows, cfg, now)
        if d.action == "AUTO_CLOSE":
            auto.append(r["url"])
        elif d.action == "TRIAGE":
            tri.append(r["url"])
    return auto, tri


@main.command(name="corral-triage")
@click.option("--idle-days", type=int, default=0,
              help="Simulate idle days when picking candidates (0 = use real values).")
@click.option("--title", default=None, help="Tab group title (default: 'Triage <date>').")
@click.option("--color", default="yellow",
              type=click.Choice(["grey", "blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange"]))
def corral_triage(idle_days, title, color):
    """Group all current TRIAGE candidates into a Dia tab group via the bridge extension."""
    cfg = cfgmod.load()
    _, urls = _candidates_from_preview(idle_days)
    if not urls:
        click.echo("No TRIAGE candidates right now.")
        return
    import datetime as dt
    t = title or f"Triage {dt.date.today().isoformat()}"
    _post_extension_command(cfg, "group", urls, t, color)


@main.command(name="corral-autoclose")
@click.option("--idle-days", type=int, default=0)
@click.option("--title", default=None, help="Tab group title (default: 'To Close <date>').")
@click.option("--color", default="red",
              type=click.Choice(["grey", "blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange"]))
def corral_autoclose(idle_days, title, color):
    """Group all current AUTO_CLOSE candidates into a Dia tab group via the bridge extension."""
    cfg = cfgmod.load()
    urls, _ = _candidates_from_preview(idle_days)
    if not urls:
        click.echo("No AUTO_CLOSE candidates right now.")
        return
    import datetime as dt
    t = title or f"To Close {dt.date.today().isoformat()}"
    _post_extension_command(cfg, "group", urls, t, color)


@main.command()
def windows():
    """List Dia windows with current profile binding (auto + override)."""
    conn = db.open_db()
    win_map = profiles_module().apply_overrides(profiles_module().resolve_live(), conn)
    wins = applescript.list_tabs()
    for w in wins:
        prof = win_map.get(w["window_id"], "<unknown>")
        click.echo(f"{w['window_id']}  profile={prof}  tabs={len(w['tabs'])}  active={w['name'][:60]!r}")


@main.command()
@click.argument("window_id")
@click.argument("profile")
def bind(window_id: str, profile: str):
    """Manually bind a Dia window id to a profile name (overrides Dia's JSON)."""
    conn = db.open_db()
    profiles_module().bind_window(conn, window_id, profile, int(time.time()))
    click.echo(f"bound {window_id} -> {profile}")


@main.command()
@click.argument("window_id")
def unbind(window_id: str):
    """Remove manual binding for a window id."""
    conn = db.open_db()
    profiles_module().unbind_window(conn, window_id)
    click.echo(f"unbound {window_id}")


@main.command()
@click.option("--port", type=int, default=None, help="UI port (defaults to config.ui_port)")
@click.option("--host", default="127.0.0.1", help="Bind host")
def serve(port: int | None, host: str):
    """Run the Flask triage UI server."""
    cfg = cfgmod.load()
    p = port if port is not None else cfg.ui_port
    app = server.create_app()
    click.echo(f"serving on http://{host}:{p}/")
    app.run(host=host, port=p)


@main.command(name="install-schedule")
def install_schedule():
    cfg = cfgmod.load()
    paths_mod.ensure_data_home()
    binary = shutil.which("dia-organizer") or sys.executable + " -m dia_organizer.cli"
    plist = scheduling.render_plist(
        binary=binary,
        interval_seconds=cfg.scan_interval_minutes * 60,
        log_path=str(paths_mod.log_path()),
        err_path=str(paths_mod.err_path()),
    )
    p = scheduling.plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(plist)
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
    subprocess.run(["launchctl", "load", str(p)], check=True)
    click.echo(f"installed: {p}")


@main.command(name="uninstall-schedule")
def uninstall_schedule():
    p = scheduling.plist_path()
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
    if p.exists():
        p.unlink()
    click.echo("uninstalled")


if __name__ == "__main__":
    main()
