"""Users, login and the change history (задание раздел 05).

Every active user may view and edit the three bases, create workers and employers, handle documents and
pick the Assigned person. Only a super user may delete a worker or employer, see the change history and
manage users. The very first start asks for the first super user instead of shipping a default password.
"""
from __future__ import annotations

import json
from datetime import timedelta
from functools import wraps

from flask import abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    is_super INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Who changed what and when, in the three bases. Rows stay after the record is deleted.
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    user_id INTEGER,
    username TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,                  -- create | update | delete
    entity TEXT NOT NULL,                  -- candidate | employer | position | case | attachment
    entity_id INTEGER,
    label TEXT NOT NULL DEFAULT '',        -- name/number of the record at the time
    field TEXT NOT NULL DEFAULT '',
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_log(entity, entity_id);
CREATE INDEX IF NOT EXISTS ix_audit_at ON audit_log(at);
"""

ENTITY_LABELS = {"candidate": "Работник", "employer": "Работодател", "position": "Длъжност", "case": "Случай",
                 "attachment": "Прикачен файл"}
AUDITED = set(ENTITY_LABELS)
# Columns not worth a history line (bookkeeping, set by the program).
SKIP_FIELDS = {"updated_at", "created_at", "status_changed_at", "ref_no", "airtable_id", "passport_scan"}

PUBLIC_ENDPOINTS = {"login", "setup", "static", "logout"}


def init(conn) -> None:
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(candidate)")}
    if "assigned_user_id" not in have:
        conn.execute("ALTER TABLE candidate ADD COLUMN assigned_user_id INTEGER REFERENCES app_user(id)"
                     " ON DELETE SET NULL")


def current_user():
    return getattr(g, "user", None)


def username() -> str:
    u = current_user()
    return (u["full_name"] or u["username"]) if u else ""


def super_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u or not u["is_super"]:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def active_users():
    return get_db().execute("SELECT id, username, full_name FROM app_user WHERE is_active=1"
                            " ORDER BY full_name, username").fetchall()


# ---------------------------------------------------------------- change history

def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def log(action, entity, entity_id, label="", field="", old="", new=""):
    if entity not in AUDITED:
        return
    u = current_user()
    get_db().execute(
        "INSERT INTO audit_log (user_id, username, action, entity, entity_id, label, field, old_value, new_value)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (u["id"] if u else None, username(), action, entity, entity_id, label, field, _txt(old), _txt(new)))


def record_label(entity, row) -> str:
    if row is None:
        return ""
    r = dict(row)
    if entity == "candidate":
        return f"№ {r.get('ref_no') or ''} {r.get('name_cyr') or r.get('name_lat') or ''}".strip()
    if entity == "employer":
        return f"№ {r.get('ref_no') or ''} {r.get('name') or ''}".strip()
    if entity == "position":
        return r.get("title") or ""
    if entity == "case":
        return f"случай {r.get('id')}"
    return ""


def log_changes(entity, entity_id, before, after: dict):
    """One history line per changed field."""
    if entity not in AUDITED:
        return
    b = dict(before) if before is not None else {}
    label = record_label(entity, {**b, **after, "id": entity_id})
    for k, v in after.items():
        if k in SKIP_FIELDS:
            continue
        if _txt(b.get(k)) != _txt(v):
            log("update", entity, entity_id, label, k, b.get(k), v)


# ---------------------------------------------------------------- routes

def register(app):
    app.permanent_session_lifetime = timedelta(hours=12)

    @app.before_request
    def _load_user():
        g.user = None
        uid = session.get("uid")
        if uid:
            g.user = get_db().execute("SELECT * FROM app_user WHERE id=? AND is_active=1", (uid,)).fetchone()
            if g.user is None:
                session.clear()
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
            return None
        if g.user is None:
            if not get_db().execute("SELECT 1 FROM app_user").fetchone():
                return redirect(url_for("setup"))
            if request.is_json or request.path.startswith("/schedule/"):
                return {"ok": False, "errors": {"login": "Влезте отново в програмата."}}, 401
            return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
        return None

    @app.context_processor
    def _user_globals():
        return {"current_user": current_user()}

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        """First start only: create the first super user."""
        d = get_db()
        if d.execute("SELECT 1 FROM app_user").fetchone():
            return redirect(url_for("login"))
        errors = {}
        if request.method == "POST":
            errors = _user_form_errors(request.form, new=True)
            if not errors:
                uid = _create_user(request.form, is_super=True)
                session.clear()
                session.permanent = True
                session["uid"] = uid
                flash("Създаден е първият потребител (супер юзър). Добавете колегите от меню „Потребители“.", "ok")
                return redirect(url_for("home"))
        return render_template("setup.html", errors=errors, values=request.form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        d = get_db()
        if not d.execute("SELECT 1 FROM app_user").fetchone():
            return redirect(url_for("setup"))
        error = ""
        if request.method == "POST":
            u = d.execute("SELECT * FROM app_user WHERE username=?",
                          (request.form.get("username", "").strip(),)).fetchone()
            if u and u["is_active"] and check_password_hash(u["password_hash"], request.form.get("password", "")):
                session.clear()
                session.permanent = True
                session["uid"] = u["id"]
                nxt = request.args.get("next") or ""
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("home"))
            error = "Грешно име или парола, или потребителят е спрян."
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        flash("Излязохте от програмата.", "ok")
        return redirect(url_for("login"))

    @app.route("/users", methods=["GET", "POST"])
    @super_required
    def users():
        d = get_db()
        errors, values = {}, {}
        if request.method == "POST":
            errors = _user_form_errors(request.form, new=True)
            values = request.form
            if not errors:
                _create_user(request.form, is_super=bool(request.form.get("is_super")))
                flash("Потребителят е добавен.", "ok")
                return redirect(url_for("users"))
        rows = d.execute("SELECT u.*, (SELECT count(*) FROM candidate c WHERE c.assigned_user_id=u.id) AS nassigned"
                         " FROM app_user u ORDER BY u.is_active DESC, u.full_name, u.username").fetchall()
        return render_template("users.html", rows=rows, errors=errors, values=values)

    @app.post("/users/<int:uid>")
    @super_required
    def user_update(uid):
        d = get_db()
        u = d.execute("SELECT * FROM app_user WHERE id=?", (uid,)).fetchone()
        if u is None:
            abort(404)
        is_super = 1 if request.form.get("is_super") else 0
        is_active = 1 if request.form.get("is_active") else 0
        if uid == current_user()["id"] and (not is_super or not is_active):
            flash("Не може да спрете или да махнете супер правата на себе си.", "error")
            return redirect(url_for("users"))
        d.execute("UPDATE app_user SET full_name=?, email=?, is_super=?, is_active=? WHERE id=?",
                  (request.form.get("full_name", "").strip(), request.form.get("email", "").strip(),
                   is_super, is_active, uid))
        pw = request.form.get("password", "")
        if pw:
            if len(pw) < 8:
                flash("Паролата трябва да е поне 8 знака. Другите промени са записани.", "error")
            else:
                d.execute("UPDATE app_user SET password_hash=? WHERE id=?", (generate_password_hash(pw), uid))
        d.commit()
        flash(f"Потребителят „{u['username']}“ е записан.", "ok")
        return redirect(url_for("users"))

    @app.route("/account", methods=["GET", "POST"])
    def account():
        """Any user changes their own password."""
        u = current_user()
        if request.method == "POST":
            if not check_password_hash(u["password_hash"], request.form.get("old_password", "")):
                flash("Старата парола не е вярна.", "error")
            elif len(request.form.get("password", "")) < 8:
                flash("Новата парола трябва да е поне 8 знака.", "error")
            elif request.form.get("password") != request.form.get("password2"):
                flash("Двете нови пароли не съвпадат.", "error")
            else:
                get_db().execute("UPDATE app_user SET password_hash=? WHERE id=?",
                                 (generate_password_hash(request.form["password"]), u["id"]))
                get_db().commit()
                flash("Паролата е сменена.", "ok")
                return redirect(url_for("home"))
        return render_template("account.html")

    @app.get("/history")
    @super_required
    def history():
        d = get_db()
        f_entity = request.args.get("entity", "")
        f_user = request.args.get("user", "")
        f_q = request.args.get("q", "").strip()
        sql, where, args = "SELECT * FROM audit_log", [], []
        if f_entity:
            where.append("entity=?")
            args.append(f_entity)
        if f_user:
            where.append("username=?")
            args.append(f_user)
        if f_q:
            where.append("(label LIKE ? OR old_value LIKE ? OR new_value LIKE ?)")
            args += [f"%{f_q}%"] * 3
        if request.args.get("record"):
            where.append("entity_id=?")
            args.append(request.args.get("record", type=int))
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = d.execute(sql + " ORDER BY id DESC LIMIT 500", args).fetchall()
        names = [r[0] for r in d.execute("SELECT DISTINCT username FROM audit_log WHERE username<>'' ORDER BY 1")]
        return render_template("history.html", rows=rows, entities=ENTITY_LABELS, f_entity=f_entity,
                               f_user=f_user, f_q=f_q, names=names)

    @app.errorhandler(403)
    def _forbidden(_exc):
        return render_template("forbidden.html"), 403


def _user_form_errors(form, new=False) -> dict:
    errors = {}
    name = form.get("username", "").strip()
    if new:
        if not name:
            errors["username"] = "Потребителско име: задължително поле"
        elif get_db().execute("SELECT 1 FROM app_user WHERE username=?", (name,)).fetchone():
            errors["username"] = "Вече има потребител с това име"
    if len(form.get("password", "")) < 8:
        errors["password"] = "Парола: поне 8 знака"
    elif form.get("password2") is not None and form.get("password") != form.get("password2"):
        errors["password2"] = "Двете пароли не съвпадат"
    return errors


def _create_user(form, is_super=False) -> int:
    d = get_db()
    uid = d.execute("INSERT INTO app_user (username, full_name, email, password_hash, is_super) VALUES (?,?,?,?,?)",
                    (form.get("username", "").strip(), form.get("full_name", "").strip(),
                     form.get("email", "").strip(), generate_password_hash(form["password"]),
                     1 if is_super else 0)).lastrowid
    d.commit()
    return uid
