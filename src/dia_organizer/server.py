from __future__ import annotations
import time
from flask import Flask, render_template, redirect, request, url_for

from dia_organizer import applescript, archive, db, snapshots, triage


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    @app.route("/")
    def index():
        return redirect(url_for("triage_page"))

    @app.route("/triage")
    def triage_page():
        conn = db.open_db()
        items = [dict(r) for r in triage.pending(conn)]
        return render_template("triage.html", items=items)

    @app.post("/triage/<int:archive_id>/keep")
    def triage_keep(archive_id: int):
        conn = db.open_db()
        triage.resolve(conn, archive_id, "keep", int(time.time()))
        return redirect(url_for("triage_page"))

    @app.post("/triage/<int:archive_id>/close")
    def triage_close(archive_id: int):
        conn = db.open_db()
        row = conn.execute("SELECT * FROM tabs WHERE archive_id=?", (archive_id,)).fetchone()
        if row is None:
            return ("not found", 404)
        archive.mark_closed(conn, archive_id, "triage:close", int(time.time()))
        try:
            applescript.close_tab(row["window_id"], row["dia_tab_id"])
        except applescript.AppleScriptError:
            pass
        triage.resolve(conn, archive_id, "close", int(time.time()))
        return redirect(url_for("triage_page"))

    @app.post("/triage/<int:archive_id>/snooze")
    def triage_snooze(archive_id: int):
        days = int(request.form.get("days", 7))
        until = int(time.time()) + days * 86_400
        conn = db.open_db()
        triage.snooze(conn, archive_id, until=until, now=int(time.time()))
        return redirect(url_for("triage_page"))

    @app.route("/archive")
    def archive_page():
        q = (request.args.get("q") or "").strip()
        results = []
        if q:
            conn = db.open_db()
            results = [dict(r) for r in archive.search(conn, q)]
        return render_template("archive.html", q=q, results=results)

    @app.post("/archive/<int:archive_id>/reopen")
    def archive_reopen(archive_id: int):
        conn = db.open_db()
        row = archive.reopen_record(conn, archive_id)
        if row is None:
            return ("not found", 404)
        try:
            applescript.make_tab(row["window_id"], row["url"])
        except applescript.AppleScriptError:
            pass
        return redirect(url_for("archive_page", q=request.args.get("q", "")))

    @app.route("/history")
    def history_page():
        return "history (todo)"

    return app
