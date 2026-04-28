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


if __name__ == "__main__":
    main()
