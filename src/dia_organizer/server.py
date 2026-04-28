from __future__ import annotations
import time
import threading
import itertools
from flask import Flask, render_template, redirect, request, url_for, jsonify

from dia_organizer import applescript, archive, db, snapshots, triage


# In-memory queue of pending commands for the Dia bridge extension.
# This lives only in the running Flask process — extension polling is the
# delivery mechanism, no persistence needed.
_ext_lock = threading.Lock()
_ext_id = itertools.count(1)
_ext_queue: list[dict] = []
_ext_results: dict[int, dict] = {}
# Latest tab dumps from extensions, keyed by profile_hint (or "_unknown_").
_ext_tab_dumps: dict[str, dict] = {}


def enqueue_extension_command(action: str, **payload) -> int:
    cmd_id = next(_ext_id)
    cmd = {"id": cmd_id, "action": action, **payload}
    with _ext_lock:
        _ext_queue.append(cmd)
    return cmd_id


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    @app.route("/")
    def index():
        return redirect(url_for("triage_page"))

    @app.get("/ext/poll")
    def ext_poll():
        with _ext_lock:
            cmds = list(_ext_queue)
            _ext_queue.clear()
        return jsonify(cmds)

    @app.post("/ext/result")
    def ext_result():
        data = request.get_json(silent=True) or {}
        cid = data.get("id")
        if cid is not None:
            with _ext_lock:
                _ext_results[cid] = data
        return ("", 204)

    @app.get("/ext/status")
    def ext_status():
        with _ext_lock:
            return jsonify({
                "queue_size": len(_ext_queue),
                "results": list(_ext_results.values())[-20:],
            })

    @app.post("/ext/tabs")
    def ext_tabs():
        import json as _json
        data = request.get_json(silent=True) or {}
        key = data.get("profile_hint") or "_unknown_"
        tabs = data.get("tabs", [])
        with _ext_lock:
            _ext_tab_dumps[key] = {"received_at": int(time.time()), "tabs": tabs}
        # Persist URL set so out-of-process scanner runs can read it.
        if key != "_unknown_":
            try:
                conn = db.open_db()
                urls = [t.get("url") for t in tabs if t.get("url")]
                conn.execute(
                    "INSERT OR REPLACE INTO extension_tab_dumps(profile, taken_at, urls_json) VALUES (?,?,?)",
                    (key, int(time.time()), _json.dumps(urls)),
                )
                conn.commit()
            except Exception:
                pass
        return ("", 204)

    @app.get("/ext/tabs-latest")
    def ext_tabs_latest():
        key = request.args.get("profile") or "_unknown_"
        with _ext_lock:
            return jsonify(_ext_tab_dumps.get(key) or {"received_at": 0, "tabs": []})

    @app.post("/ext/enqueue")
    def ext_enqueue():
        data = request.get_json(silent=True) or {}
        action = data.get("action")
        if not action:
            return jsonify({"error": "missing action"}), 400
        # Forward all fields except 'action' so per-action params (profile_hint,
        # urls, title, color, etc.) reach the extension intact.
        payload = {k: v for k, v in data.items() if k != "action"}
        cid = enqueue_extension_command(action, **payload)
        return jsonify({"id": cid})

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
        conn = db.open_db()
        rows = [dict(r) for r in snapshots.list_all(conn)]
        return render_template("history.html", snapshots=rows, detail=None)

    @app.route("/history/<int:snapshot_id>")
    def history_detail(snapshot_id: int):
        from dia_organizer import profiles as _p
        conn = db.open_db()
        windows = applescript.list_tabs()
        win_map = _p.apply_overrides(_p.resolve_live(), conn)
        plan = snapshots.plan_rollback(conn, snapshot_id, windows, win_map, replace=False)
        plan["snapshot_id"] = snapshot_id
        rows = [dict(r) for r in snapshots.list_all(conn)]
        return render_template("history.html", snapshots=rows, detail=plan)

    @app.post("/history/<int:snapshot_id>/rollback")
    def history_rollback(snapshot_id: int):
        from dia_organizer import profiles as _p
        replace = "replace" in request.form
        conn = db.open_db()
        windows = applescript.list_tabs()
        win_map = _p.apply_overrides(_p.resolve_live(), conn)
        if replace:
            snapshots.take(conn, windows, win_map,
                            label=f"pre-rollback-of-{snapshot_id}",
                            trigger="pre-rollback", retention="manual",
                            now=int(time.time()))
        plan = snapshots.plan_rollback(conn, snapshot_id, windows, win_map, replace=replace)
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
        return redirect(url_for("history_page"))

    return app
