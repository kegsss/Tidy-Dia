from __future__ import annotations
import time
import click

from dia_organizer import applescript, archive, config as cfgmod, db, scanner, snapshots, triage as triage_mod


@click.group()
def main():
    """dia-organizer — tame Dia tab sprawl."""


@main.command()
@click.option("--dry-run", is_flag=True, help="Force dry-run regardless of config")
def scan(dry_run: bool):
    cfg = cfgmod.load()
    if dry_run:
        import datetime as dt
        cfg.dry_run_until = dt.date.today() + dt.timedelta(days=1)
    conn = db.open_db()
    res = scanner.run_scan(conn, cfg)
    click.echo(
        f"status={res.get('status')} dry_run={res.get('dry_run')} "
        f"closed={res.get('closed', 0)} triaged={res.get('triaged', 0)} "
        f"rate_limited={res.get('rate_limited', 0)}"
    )


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
    win_map = profiles_module().resolve_live()
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
    win_map = profiles_module().resolve_live()
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


if __name__ == "__main__":
    main()
