"""Flask web app: candidates, employers, positions, cases, templates, PDF generation."""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.utils import secure_filename

from . import db as dbm
from . import ai_text, auth, dashboard, forms, mailer, mrz, pipeline, portal, render
from . import schedule as sched
from .grammar import parse_date
from .context import LIST_FIELDS, PLACEHOLDERS, build_context, flatten, missing_fields
from .db import get_db

ROOT = Path(__file__).resolve().parent.parent
# Starting values of a new case (contract terms). Per visa type only the contract length differs.
CASE_DEFAULTS = {"contract_months": 36, "probation_months": 6, "currency": "евро", "pay_day": "30",
                 "leave_days": 20, "extra_leave_days": 0, "notice_months": 3,
                 "working_time": "пълно работно време по график на смени при условията на сумирано "
                                 "изчисляване на работното време /СИРВ/",
                 "doc_city": "София"}
CONTRACT_MONTHS = {"3 години": 36, "Удължаване": 12, "3 месеца": 3, "1 година": 12}
EDITABLE_TEXT = {k for k, _ in sched.TEXT_FIELDS}
EDITABLE_DATES = {k for k, _ in sched.DATE_FIELDS}
MASTERS_DIR = ROOT / "masters"


def default_data_dir() -> Path:
    return Path(os.environ.get("DOCAUTOMATE_DATA", ROOT / "data"))


def create_app(data_dir: Path | None = None, testing: bool = False) -> Flask:
    app = Flask(__name__)
    data_dir = Path(data_dir or default_data_dir())
    for sub in ("templates", "generated", "scans", "attachments"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    app.config.update(
        DATA_DIR=str(data_dir),
        DATABASE=str(data_dir / "docautomate.db"),
        SECRET_KEY=_secret_key(data_dir),
        MAX_CONTENT_LENGTH=30 * 1024 * 1024,
        TESTING=testing,
    )
    conn = dbm.connect(Path(app.config["DATABASE"]))
    dbm.init_db(conn)
    auth.init(conn)
    mailer.init(conn)
    conn.commit()
    install_masters(conn, data_dir / "templates")
    conn.close()
    app.teardown_appcontext(dbm.close_db)
    portal.register(app)  # before auth: Synchro requests are passed on without Docautomate's login
    auth.register(app)
    dashboard.register(app)
    _register(app)
    if not testing and not os.environ.get("DOCAUTOMATE_NO_MAILER"):
        mailer.start_scheduler(app, lambda: dbm.connect(Path(app.config["DATABASE"])))
    return app


def _secret_key(data_dir: Path) -> str:
    p = data_dir / ".secret_key"
    if not p.exists():
        p.write_text(secrets.token_hex(32))
    return p.read_text().strip()


def install_masters(conn, templates_dir: Path) -> None:
    """Copy the shipped master templates into data/templates once and link them to case types."""
    manifest = MASTERS_DIR / "manifest.json"
    if not manifest.exists():
        return
    items = json.loads(manifest.read_text(encoding="utf-8"))
    # master_key never changes, even after staff replace the file, so a master is installed only once.
    # Rows from before master_key existed are matched once by their original file name or name.
    for item in items:
        fname = item["file"]
        conn.execute("UPDATE doc_template SET master_key=? WHERE id=(SELECT id FROM doc_template WHERE is_master=1"
                     " AND master_key IS NULL AND (filename=? OR name=?) ORDER BY id LIMIT 1)"
                     " AND NOT EXISTS (SELECT 1 FROM doc_template WHERE master_key=?)",
                     (fname, fname, item["name"], fname))
    # An old master whose file AND name were both changed cannot be matched. Rather than risk a second
    # active copy, nothing more is installed while such a row exists (staff can upload a master by hand).
    legacy_unmatched = conn.execute(
        "SELECT count(*) FROM doc_template WHERE is_master=1 AND master_key IS NULL").fetchone()[0]
    for i, item in enumerate(items):
        fname = item["file"]
        if conn.execute("SELECT 1 FROM doc_template WHERE master_key=?", (fname,)).fetchone():
            continue
        if legacy_unmatched:
            continue
        src = MASTERS_DIR / fname
        if not src.exists():
            continue
        shutil.copy2(src, templates_dir / fname)
        check = render.check_template(src)
        tid = conn.execute(
            "INSERT INTO doc_template (name, filename, is_master, master_key, sort_order, placeholders,"
            " countries, exclude_countries) VALUES (?,?,?,?,?,?,?,?)",
            (item["name"], fname, 1, fname, (i + 1) * 10, ",".join(sorted(check.used)),
             item.get("countries", ""), item.get("exclude_countries", "")),
        ).lastrowid
        _link_case_types(conn, tid, item)
    # One time: bring masters installed by older versions to the sets of the задание (раздел 04).
    if not dbm.step_done(conn, "zadanie_template_sets"):
        for i, item in enumerate(items):
            t = conn.execute("SELECT id, countries, exclude_countries FROM doc_template WHERE master_key=?",
                             (item["file"],)).fetchone()
            if not t:
                continue
            conn.execute("DELETE FROM case_type_template WHERE template_id=?", (t["id"],))
            _link_case_types(conn, t["id"], item)
            conn.execute("UPDATE doc_template SET sort_order=?, countries=?, exclude_countries=? WHERE id=?",
                         ((i + 1) * 10, t["countries"] or item.get("countries", ""),
                          t["exclude_countries"] or item.get("exclude_countries", ""), t["id"]))
    conn.commit()


def _link_case_types(conn, template_id, item):
    for ct_name in item.get("case_types", []):
        ct = conn.execute("SELECT id FROM case_type WHERE name=?", (ct_name,)).fetchone()
        if ct:
            conn.execute("INSERT OR IGNORE INTO case_type_template VALUES (?,?)", (ct["id"], template_id))


# ---------------------------------------------------------------- helpers

def _one(sql, *args):
    row = get_db().execute(sql, args).fetchone()
    if row is None:
        abort(404)
    return row


def _insert(table, values: dict) -> int:
    cols = ", ".join(values)
    q = ", ".join("?" * len(values))
    d = get_db()
    cur = d.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({q})', list(values.values()))
    if table in auth.AUDITED:
        row = d.execute(f'SELECT * FROM "{table}" WHERE id=?', (cur.lastrowid,)).fetchone()
        auth.log("create", table, cur.lastrowid, auth.record_label(table, row))
    d.commit()
    return cur.lastrowid


def _update(table, row_id, values: dict, touch=True) -> None:
    """Every edit of the bases goes through here, so the change history sees each changed field."""
    d = get_db()
    before = d.execute(f'SELECT * FROM "{table}" WHERE id=?', (row_id,)).fetchone() if table in auth.AUDITED else None
    sets = ", ".join(f"{k}=?" for k in values)
    if touch:
        sets += ", updated_at=datetime('now','localtime')"
    d.execute(f'UPDATE "{table}" SET {sets} WHERE id=?', [*values.values(), row_id])
    if table in auth.AUDITED:
        auth.log_changes(table, row_id, before, values)
    d.commit()


def _countries():
    return get_db().execute("SELECT * FROM country ORDER BY name").fetchall()


def _safe_name(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n]+', " ", text or "").strip()
    return re.sub(r"\s+", " ", text)[:80] or "документ"


def _iso_set(text) -> set[str]:
    return {x.strip().upper() for x in (text or "").replace(";", ",").split(",") if x.strip()}


def template_applies(t, iso3) -> bool:
    """Country rule of a template (задание 04): RU contract for UZB/KGZ, EN for the rest, letter for IND/NPL."""
    only, exclude = _iso_set(t["countries"]), _iso_set(t["exclude_countries"])
    iso3 = (iso3 or "").upper()
    if only and iso3 not in only:
        return False
    return not (exclude and iso3 in exclude)


def _templates_for_case_type(case_type_id, iso3=None, by_country=True):
    rows = get_db().execute(
        "SELECT t.* FROM doc_template t JOIN case_type_template ct ON ct.template_id=t.id"
        " WHERE ct.case_type_id=? AND t.is_active=1 ORDER BY t.sort_order, t.name",
        (case_type_id,),
    ).fetchall()
    return [t for t in rows if template_applies(t, iso3)] if by_country else rows


def _case_iso3(case_id):
    r = get_db().execute('SELECT co.iso3 FROM "case" c JOIN candidate ca ON ca.id=c.candidate_id'
                         " LEFT JOIN country co ON co.id=ca.citizenship_id WHERE c.id=?", (case_id,)).fetchone()
    return r["iso3"] if r else None


def _template_path(t) -> Path:
    return Path(dbm.data_dir()) / "templates" / t["filename"]


def _integrity_message(exc) -> str:
    msg = str(exc)
    if "UNIQUE" in msg and "employer.name" in msg:
        return "Вече има работодател с това име."
    if "UNIQUE" in msg and "position" in msg:
        return "Този работодател вече има такава длъжност."
    if "UNIQUE" in msg and "country" in msg:
        return "Вече има държава с това име или код."
    if "FOREIGN KEY" in msg:
        return "Записът се използва другаде и не може да бъде изтрит."
    return f"Грешка в базата: {msg}"


# ---------------------------------------------------------------- routes

def _register(app: Flask) -> None:  # noqa: C901  (one place for all routes keeps it easy to follow)
    import sqlite3

    @app.context_processor
    def _globals():
        return {"GENDER": dict(forms.GENDER), "now": datetime.now(), "VISA_TYPES": dbm.VISA_TYPES}

    @app.template_filter("bgdate")
    def _bgdate(v):
        from .grammar import fmt_date
        return fmt_date(v)

    @app.errorhandler(sqlite3.IntegrityError)
    def _integrity(exc):
        flash(_integrity_message(exc), "error")
        return redirect(request.referrer or url_for("home"))

    # ------------------------------------------------------------ home
    # ------------------------------------------------------------ candidates
    @app.get("/candidates")
    def candidates():
        """База Работници: table with search, filters (employer, country, visa type) and grouping."""
        d = get_db()
        q = request.args.get("q", "").strip()
        f_emp = request.args.get("employer", type=int)
        f_country = request.args.get("country", type=int)
        f_visa = request.args.get("visa", "").strip()
        group = request.args.get("group") == "employer"
        sql = ("SELECT ca.*, co.name AS citizenship, e.name AS employer, p.title AS position FROM candidate ca"
               " LEFT JOIN country co ON co.id=ca.citizenship_id LEFT JOIN employer e ON e.id=ca.employer_id"
               " LEFT JOIN position p ON p.id=ca.position_id")
        where, args = [], []
        if q:
            where.append("(ca.name_cyr LIKE ? OR ca.name_lat LIKE ? OR ca.passport_no LIKE ? OR ca.phone LIKE ?"
                         " OR CAST(ca.ref_no AS TEXT)=?)")
            args += [f"%{q}%"] * 4 + [q]
        if f_emp:
            where.append("ca.employer_id=?")
            args.append(f_emp)
        if f_country:
            where.append("ca.citizenship_id=?")
            args.append(f_country)
        if f_visa == "-":
            where.append("ca.visa_type=''")
        elif f_visa:
            where.append("ca.visa_type=?")
            args.append(f_visa)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY e.name IS NULL, e.name, ca.name_cyr" if group else " ORDER BY ca.updated_at DESC"
        rows = d.execute(sql + " LIMIT 1000", args).fetchall()
        groups = []
        if group:
            for r in rows:
                key = r["employer"] or "Без работодател"
                if not groups or groups[-1][0] != key:
                    groups.append((key, []))
                groups[-1][1].append(r)
        return render_template(
            "candidates.html", rows=rows, groups=groups, q=q, group=group,
            f_emp=f_emp, f_country=f_country, f_visa=f_visa,
            employers=d.execute("SELECT id, name FROM employer ORDER BY name").fetchall(),
            countries=d.execute("SELECT DISTINCT co.id, co.name FROM candidate ca JOIN country co"
                                " ON co.id=ca.citizenship_id ORDER BY co.name").fetchall())

    @app.route("/candidates/new", methods=["GET", "POST"])
    @app.route("/candidates/<int:cid>", methods=["GET", "POST"])
    def candidate(cid=None):
        d = get_db()
        row = _one("SELECT * FROM candidate WHERE id=?", cid) if cid else None
        values = dict(row) if row else {"employer_id": request.args.get("employer_id", type=int)}
        errors = {}
        if request.method == "POST":
            try:
                data, errs = {}, {}
                try:
                    data = forms.parse_form(forms.CANDIDATE, request.form)
                except forms.FormError as exc:
                    errs.update(exc.errors)
                data.update(_worker_links(request.form, errs))
                if errs:
                    raise forms.FormError(errs)
                if row:
                    _update("candidate", cid, data)
                else:
                    cid = _insert("candidate", data)
                scan = request.files.get("passport_scan")
                if scan and scan.filename:
                    _save_scan(cid, scan)
                flash("Работникът е записан.", "ok")
                return redirect(url_for("candidate", cid=cid))
            except forms.FormError as exc:
                errors = exc.errors
                values = {**values, **request.form.to_dict()}
        cases = d.execute(
            'SELECT c.*, e.name AS employer, ct.name AS ctype FROM "case" c JOIN employer e ON e.id=c.employer_id'
            " JOIN case_type ct ON ct.id=c.case_type_id WHERE c.candidate_id=? ORDER BY c.created_at DESC",
            (cid or 0,)).fetchall()
        return render_template("candidate.html", row=row, values=values, errors=errors,
                               fields=forms.CANDIDATE, countries=_countries(), cases=cases,
                               ocr=mrz.ocr_available(), attach_groups=dbm.WORKER_ATTACHMENTS,
                               files=_attachments("worker", cid) if cid else {}, **_worker_choices(),
                               info=sched.addition_info(row) if row else None,
                               statuses=sched.ALL_STATUSES, sched_text=sched.TEXT_FIELDS,
                               sched_dates=sched.DATE_FIELDS,
                               history=d.execute("SELECT * FROM status_history WHERE candidate_id=?"
                                                 " ORDER BY id DESC", (cid or 0,)).fetchall(),
                               plan=worker_doc_plan(cid) if row else None, users=auth.active_users(),
                               gens=_worker_generations(cid) if row else ([], {}), pdf=render.converter_name(),
                               step=worker_step(cid) if row else None, run=_pop_run(cid))

    # ------------------------------------------------------------ Справки (График)
    sort_fields = {k for k, _ in sched.DATE_FIELDS} | {"created_at"}

    @app.get("/schedule")
    def schedule():
        """The working table: worker and employer columns, editable dates and status, delay colours."""
        d = get_db()
        f_emps = [int(x) for x in request.args.getlist("employer") if x.isdigit()]
        f_visa = request.args.get("visa", "").strip()
        f_status = request.args.get("status", "").strip()
        f_delay = request.args.get("delay", "").strip()
        f_assigned = request.args.get("assigned", "").strip()
        group = request.args.get("group", "")
        sort = request.args.get("sort", "")
        desc = request.args.get("dir") == "desc"
        sql = ("SELECT ca.*, co.name AS citizenship, e.name AS employer,"
               " coalesce(nullif(u.full_name, ''), u.username, 'Без отговорник') AS assigned FROM candidate ca"
               " LEFT JOIN country co ON co.id=ca.citizenship_id LEFT JOIN employer e ON e.id=ca.employer_id"
               " LEFT JOIN app_user u ON u.id=ca.assigned_user_id")
        where, args = [], []
        if f_assigned == "-":
            where.append("ca.assigned_user_id IS NULL")
        elif f_assigned.isdigit():
            where.append("ca.assigned_user_id=?")
            args.append(int(f_assigned))
        if f_emps:
            where.append(f"ca.employer_id IN ({','.join('?' * len(f_emps))})")
            args += f_emps
        if f_visa:
            where.append("ca.visa_type=?")
            args.append(f_visa)
        if f_status:
            where.append("ca.status=?")
            args.append(f_status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = [{"r": r, "info": sched.addition_info(r)} for r in d.execute(sql, args).fetchall()]
        if f_delay in ("red", "orange"):
            rows = [x for x in rows if x["info"]["delay"] == f_delay]
        if sort in sort_fields:
            # empty dates always go last, whichever direction
            filled = sorted((x for x in rows if x["r"][sort]), key=lambda x: x["r"][sort], reverse=desc)
            rows = filled + [x for x in rows if not x["r"][sort]]
        else:
            rows.sort(key=lambda x: x["r"]["ref_no"] or 0)
        group_keys = {"status": "status", "visa": "visa_type", "employer": "employer", "contact": "contact",
                      "assigned": "assigned"}
        groups = []
        if group in group_keys:
            col = group_keys[group]
            order = {s: i for i, s in enumerate(sched.ALL_STATUSES)} if group == "status" else None
            def gkey(x):
                v = x["r"][col] or ""
                return (order.get(v, 99), v) if order else (v == "", v)
            for x in sorted(rows, key=gkey):
                label = x["r"][col] or "(празно)"
                if not groups or groups[-1][0] != label:
                    groups.append((label, []))
                groups[-1][1].append(x)
        return render_template(
            "schedule.html", rows=rows, groups=groups, group=group, sort=sort, desc=desc,
            f_emps=f_emps, f_visa=f_visa, f_status=f_status, f_delay=f_delay, f_assigned=f_assigned,
            users=auth.active_users(),
            employers=d.execute("SELECT id, name FROM employer ORDER BY name").fetchall(),
            statuses=sched.ALL_STATUSES, main_statuses=sched.STATUSES, date_fields=sched.DATE_FIELDS)

    def set_status(cid, new_status, by=None):
        """Manual status change: the only way a status moves. Writes the history row."""
        d = get_db()
        by = auth.username() if by is None else by
        row = _one("SELECT * FROM candidate WHERE id=?", cid)
        if new_status not in sched.ALL_STATUSES:
            raise ValueError("невалиден статус")
        if new_status == row["status"]:
            return False
        d.execute("UPDATE candidate SET status=?, status_changed_at=datetime('now','localtime'),"
                  " updated_at=datetime('now','localtime') WHERE id=?", (new_status, cid))
        d.execute("INSERT INTO status_history (candidate_id, old_status, new_status, changed_by) VALUES (?,?,?,?)",
                  (cid, row["status"], new_status, by))
        auth.log("update", "candidate", cid, auth.record_label("candidate", row), "status", row["status"], new_status)
        d.commit()
        return True

    @app.post("/schedule/<int:cid>")
    def schedule_update(cid):
        """Save one or more График fields (inline table edit sends JSON; the profile sends a form).
        Dates and the incoming number never change the status (задание 03)."""
        _one("SELECT id FROM candidate WHERE id=?", cid)
        data = request.get_json(silent=True) or request.form.to_dict()
        values, errors = {}, {}
        if "assigned_user_id" in data:
            raw = str(data["assigned_user_id"] or "").strip()
            if raw == "":
                values["assigned_user_id"] = None
            elif raw.isdigit() and any(u["id"] == int(raw) for u in auth.active_users()):
                values["assigned_user_id"] = int(raw)
            else:
                errors["assigned_user_id"] = "Assigned: изберете активен потребител"
        for k, v in data.items():
            if k in EDITABLE_TEXT:
                values[k] = str(v).strip()
            elif k in EDITABLE_DATES:
                try:
                    values[k] = parse_date(str(v).strip())
                except ValueError as exc:
                    errors[k] = f"{sched.EDITABLE[k]}: {exc}"
        if "status" in data and not errors:
            try:
                set_status(cid, str(data["status"]).strip())
            except ValueError as exc:
                errors["status"] = f"Статус: {exc}"
        if values and not errors:
            _update("candidate", cid, values)
        row = get_db().execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()
        info = sched.addition_info(row)
        if request.is_json:
            return jsonify(ok=not errors, errors=errors, status=row["status"], delay=info["delay"],
                           assigned_user_id=row["assigned_user_id"],
                           days_in_status=info["days_in_status"], residence_days=info["residence_days"],
                           residence_band=info["residence_band"],
                           values={k: (_iso_to_bg(row[k]) if k in EDITABLE_DATES else row[k]) for k in values
                                   if k != "assigned_user_id"}), \
                (200 if not errors else 422)
        for e in errors.values():
            flash(e, "error")
        if not errors:
            flash("Данните от графика са записани.", "ok")
        return redirect(url_for("candidate", cid=cid) + "#schedule")

    # ------------------------------------------------------------ documents from the worker profile
    def _case_type_for_visa(visa_type):
        d = get_db()
        if visa_type == "Удължаване":
            return d.execute("SELECT * FROM case_type WHERE is_extension=1 ORDER BY sort_order LIMIT 1").fetchone()
        return d.execute("SELECT * FROM case_type WHERE is_extension=0 AND residence_period=? ORDER BY sort_order"
                         " LIMIT 1", (visa_type,)).fetchone()

    def worker_doc_plan(cid):
        """What „Генерирай документи“ would do now: the case type from „Тип виза“, the existing case (if any),
        and each template of the set with its missing fields (задание 04, стъпки 01-03)."""
        d = get_db()
        w = _one("SELECT ca.*, co.iso3 FROM candidate ca LEFT JOIN country co ON co.id=ca.citizenship_id"
                 " WHERE ca.id=?", cid)
        plan = {"error": "", "case_type": None, "case_id": None, "templates": []}
        if not w["visa_type"]:
            plan["error"] = "Изберете „Тип виза“ в профила. Той определя кои бланки се генерират."
            return plan
        ct = _case_type_for_visa(w["visa_type"])
        if not ct:
            plan["error"] = (f"За тип виза „{w['visa_type']}“ още няма зададен комплект бланки"
                             " (в заданието списъкът за 1 година е за уточняване).")
            return plan
        plan["case_type"] = ct
        case = d.execute('SELECT id FROM "case" WHERE candidate_id=? AND case_type_id=? ORDER BY id DESC LIMIT 1',
                         (cid, ct["id"])).fetchone()
        if case:
            plan["case_id"] = case["id"]
        if not w["employer_id"]:
            plan["error"] = "Изберете работодател в профила."
            return plan
        # the profile is the source of truth for employer and position; the case keeps the contract terms
        case_row = d.execute('SELECT * FROM "case" WHERE id=?', (case["id"],)).fetchone() if case else None
        ctx = _worker_context(d, w, ct, dict(case_row) if case_row else None)
        for t in _templates_for_case_type(ct["id"], w["iso3"]):
            used = set(filter(None, t["placeholders"].split(",")))
            plan["templates"].append({"t": t, "missing": [(k, PLACEHOLDERS[k][0])
                                                          for k in missing_fields(ctx, used)]})
        return plan

    def _worker_context(d, w, ct, case):
        """Preview context from the worker profile (employer, position) and the case terms; when the worker
        has no case yet, the defaults a new case would get. Writes nothing."""
        from .context import assemble, housing_workers
        emp = d.execute("SELECT * FROM employer WHERE id=?", (w["employer_id"],)).fetchone()
        pos = d.execute("SELECT * FROM position WHERE id=?", (w["position_id"],)).fetchone() if w["position_id"] else None

        def country(i):
            return d.execute("SELECT * FROM country WHERE id=?", (i,)).fetchone() if i else None
        case = case or {**CASE_DEFAULTS, "contract_months": CONTRACT_MONTHS.get(w["visa_type"], 36)}
        ctx = assemble(dict(w), dict(emp), dict(pos) if pos else {}, case, dict(ct),
                       country(w["citizenship_id"]), country(w["birth_country_id"]))
        ctx["housing_workers"] = housing_workers(d, w)
        return ctx

    def _generate_for_worker(cid):
        """Pick the set by visa type, create or update the worker's case, fill the set.
        Returns (ok, message) for a flash; ok is False when nothing usable was generated."""
        d = get_db()
        plan = worker_doc_plan(cid)
        if plan["error"]:
            return False, plan["error"]
        w = d.execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()
        case_id = plan["case_id"]
        if case_id:
            d.execute('UPDATE "case" SET employer_id=?, position_id=?, updated_at=datetime(\'now\',\'localtime\')'
                      " WHERE id=?", (w["employer_id"], w["position_id"], case_id))
            d.commit()
        else:
            case_id = _insert("case", {**CASE_DEFAULTS, "contract_months": CONTRACT_MONTHS.get(w["visa_type"], 36),
                                       "candidate_id": cid, "employer_id": w["employer_id"],
                                       "position_id": w["position_id"], "case_type_id": plan["case_type"]["id"]})
        gen_id, errors = generate_case(case_id)
        missing = sum(1 for t in plan["templates"] if t["missing"])
        if gen_id is None:
            return False, errors[0] if errors else "Нищо не е генерирано."
        if errors:
            return False, "Част от документите не са готови: " + "; ".join(errors)
        msg = f"Документите са генерирани ({len(plan['templates'])}). Свалете ги в „Документи за Миграция“."
        if missing:
            msg += f" В {missing} от тях има празни полета (излизат като „……“)."
        return True, msg

    @app.post("/candidates/<int:cid>/generate")
    def worker_generate(cid):
        """„Генерирай документи“ from the worker profile."""
        _one("SELECT id FROM candidate WHERE id=?", cid)
        ok, msg = _generate_for_worker(cid)
        flash(msg, "ok" if ok else "error")
        return redirect(url_for("candidate", cid=cid) + "#documents")

    # ------------------------------------------------------------ pipeline: „Следваща стъпка“
    def _pop_run(cid):
        r = session.get("pipeline_run")
        if r and cid and r.get("cid") == cid:
            session.pop("pipeline_run")
            return r
        return None

    def worker_step(cid):
        d = get_db()
        w = _one("SELECT ca.*, co.iso3 FROM candidate ca LEFT JOIN country co ON co.id=ca.citizenship_id"
                 " WHERE ca.id=?", cid)
        pos = d.execute("SELECT * FROM position WHERE id=?", (w["position_id"],)).fetchone() if w["position_id"] else None
        cats = {r["category"] for r in d.execute("SELECT DISTINCT category FROM attachment WHERE owner_type='worker'"
                                                 " AND owner_id=?", (cid,))}
        nxt = pipeline.next_status(w["status"], w["visa_type"])
        step = pipeline.plan_step(dict(w), attachments=cats, position=dict(pos) if pos else None,
                                  doc_plan=worker_doc_plan(cid) if nxt == "Готови документи" else None,
                                  iso3=w["iso3"] or "")
        pos_url = url_for("position", pid=w["position_id"]) + "#ai-panel" if w["position_id"] else "#cand-form"
        for c in step.checks:
            if c.link == "position-ai":
                c.link = pos_url
        return step, pipeline.deadlines(dict(w))

    @app.post("/candidates/<int:cid>/next-step")
    def worker_next_step(cid):
        """Move the worker to the next status of the visa type's path, after the checks (задание 03:
        the status still changes only on this manual click). Generates the documents where the step says so."""
        back = url_for("candidate", cid=cid) + "#pipeline"
        step, _ = worker_step(cid)
        expected = request.form.get("expected", "")
        if expected and expected != step.next:
            flash("Статусът е сменен междувременно. Прегледайте стъпката отново.", "error")
            return redirect(back)
        if not step.next:
            flash(step.note or "Няма следваща стъпка.", "error")
            return redirect(back)
        if step.blocked:
            missing = [c.label for c in step.checks if not c.ok and c.hard]
            flash(f"„{step.next}“ още не може: " + "; ".join(missing), "error")
            return redirect(back)
        if step.generate:
            ok, msg = _generate_for_worker(cid)
            if not ok:
                flash(f"Статусът остава „{step.current}“, защото документите не се генерираха: {msg}", "error")
                return redirect(back)
            flash(msg, "ok")
        set_status(cid, step.next)
        text = f"Статус: „{step.current}“ → „{step.next}“."
        short = [c.label for c in step.warnings if not c.blank]
        if short:
            text += " Препоръчително: " + "; ".join(short) + "."
        flash(text, "ok")
        return redirect(back)

    def _ai_texts_for(cid, w):
        """Before „Готови документи“: write the missing justification and job description with AI.
        Fills only empty fields of the position and saves them. Returns lines for the run summary."""
        if not w["position_id"]:
            return []
        d = get_db()
        pos = dict(d.execute("SELECT * FROM position WHERE id=?", (w["position_id"],)).fetchone())
        kinds = []
        if w["visa_type"] == "Удължаване":
            if not (pos.get("obosnovka_ext") or pos.get("obosnovka") or "").strip():
                kinds.append("obosnovka_ext")
        elif w["visa_type"] != "3 месеца" and not (pos.get("obosnovka") or "").strip():
            kinds.append("obosnovka")
        if not (pos.get("dh_duties") or "").strip():
            kinds.append("dh")
        if not kinds:
            return []
        if not ai_text.ai_available():
            return ["AI не е включен (няма ANTHROPIC_API_KEY в .env), затова обосновката и ДХ не са написани сами."]
        emp = dict(d.execute("SELECT * FROM employer WHERE id=?", (w["employer_id"],)).fetchone() or {})
        out, names = [], {"obosnovka": "Обосновката", "obosnovka_ext": "Обосновката за удължаване",
                          "dh": "Длъжностната характеристика"}
        for kind in kinds:
            dr = ai_text.draft(kind, pos, emp)
            if dr.source != "ai":  # never save the fallback sentences with their [placeholders]
                out.append(f"{names[kind]} не е написана: " + " ".join(dr.warnings[-1:]))
                continue
            fields = {k: v for k, v in dr.fields.items() if not (pos.get(k) or "").strip()}
            if fields:
                _update("position", pos["id"], fields)
                pos.update(fields)
                out.append(f"{names[kind]} е написана с AI и записана в длъжността. Прегледайте я.")
        return out

    def run_pipeline(cid):
        """„Пусни процеса“: walk the worker along the path of the visa type as far as the data allows.
        Each move is the same manual status change as the step button (checks, documents, history)."""
        done, notes, stop = [], [], None
        for _ in range(len(sched.STATUSES) + 1):
            step, _ = worker_step(cid)
            if not step.next:
                stop = {"kind": "end", "text": step.note or "Няма следваща стъпка.", "items": []}
                break
            if step.next == "Готови документи":
                w = _one("SELECT * FROM candidate WHERE id=?", cid)
                ai_lines = _ai_texts_for(cid, w)
                notes += ai_lines
                if ai_lines:
                    step, _ = worker_step(cid)
            blockers = step.run_blockers
            if blockers:
                stop = {"kind": "blocked", "text": f"Спря преди „{step.next}“. Попълнете:",
                        "items": [[c.label, c.link] for c in blockers]}
                break
            if step.manual:
                stop = {"kind": "manual", "text": step.manual, "items": []}
                break
            if step.generate:
                ok, msg = _generate_for_worker(cid)
                if not ok:
                    stop = {"kind": "error", "text": f"Спря на „{step.current}“: документите не се генерираха. {msg}",
                            "items": [["Документи за Миграция", "#documents"]]}
                    break
                notes.append(f"При „{step.next}“: {msg}")
            set_status(cid, step.next)
            done.append([step.current, step.next])
        return {"done": done, "notes": notes, "stop": stop}

    @app.post("/candidates/<int:cid>/run")
    def worker_run(cid):
        """„Пусни процеса“ from the profile or the workers list."""
        _one("SELECT id FROM candidate WHERE id=?", cid)
        session["pipeline_run"] = {"cid": cid, **run_pipeline(cid)}
        return redirect(url_for("candidate", cid=cid) + "#pipeline")

    def _worker_generations(cid):
        d = get_db()
        gens = d.execute('SELECT g.*, ct.name AS ctype FROM generation g JOIN "case" c ON c.id=g.case_id'
                         " JOIN case_type ct ON ct.id=c.case_type_id WHERE c.candidate_id=?"
                         " ORDER BY g.created_at DESC, g.id DESC LIMIT 20", (cid,)).fetchall()
        files = {g["id"]: d.execute("SELECT * FROM generated_file WHERE generation_id=? ORDER BY id",
                                    (g["id"],)).fetchall() for g in gens}
        return gens, files

    def _worker_choices():
        d = get_db()
        return {
            "employers": d.execute("SELECT id, name FROM employer ORDER BY name").fetchall(),
            "positions": d.execute("SELECT id, employer_id, title, nkpd FROM position ORDER BY title").fetchall(),
            "addresses": d.execute("SELECT id, employer_id, address FROM employer_address"
                                   " ORDER BY employer_id, sort_order, id").fetchall(),
        }

    def _worker_links(form, errs) -> dict:
        """Employer (required, must exist), position (employer's list or typed new), work address."""
        d = get_db()
        out = {"employer_id": None, "position_id": None, "workplace_address": ""}
        raw = form.get("employer_id", "").strip()
        emp = d.execute("SELECT id FROM employer WHERE id=?", (int(raw),)).fetchone() if raw.isdigit() else None
        if not emp:
            errs["employer_id"] = "Работодател: изберете работодател от списъка"
            return out
        eid = out["employer_id"] = emp["id"]
        new_title = re.sub(r"\s+", " ", form.get("position_new", "")).strip()
        praw = form.get("position_id", "").strip()
        if new_title:
            # SQLite lower() knows only Latin letters, so compare in Python (Готвач = готвач)
            p = next((r for r in d.execute("SELECT id, title FROM position WHERE employer_id=?", (eid,))
                      if r["title"].casefold() == new_title.casefold()), None)
            if p:
                out["position_id"] = p["id"]
            elif not errs:  # create the new position only when the whole form is valid
                out["position_id"] = _insert("position", {"employer_id": eid, "title": new_title})
        elif praw.isdigit():
            p = d.execute("SELECT id, employer_id FROM position WHERE id=?", (int(praw),)).fetchone()
            if not p or p["employer_id"] != eid:
                errs["position_id"] = "Длъжност: не е на избрания работодател"
            else:
                out["position_id"] = p["id"]
        addr = form.get("workplace_address", "").strip()
        if addr:
            if not d.execute("SELECT 1 FROM employer_address WHERE employer_id=? AND address=?",
                             (eid, addr)).fetchone():
                errs["workplace_address"] = "Адрес на месторабота: не е от адресите на избрания работодател"
            out["workplace_address"] = addr
        return out

    def _save_scan(cid, upload):
        ext = Path(upload.filename).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".pdf", ".tif", ".tiff", ".bmp", ".webp"):
            flash("Сканът не е записан: файлът трябва да е снимка (JPG, PNG) или PDF.", "error")
            return None
        name = f"candidate-{cid}-{datetime.now():%Y%m%d%H%M%S}{ext}"
        upload.save(Path(dbm.data_dir()) / "scans" / name)
        _update("candidate", cid, {"passport_scan": name}, touch=False)
        return name

    @app.get("/candidates/<int:cid>/scan")
    def candidate_scan(cid):
        row = _one("SELECT passport_scan FROM candidate WHERE id=?", cid)
        if not row["passport_scan"]:
            abort(404)
        return send_file(Path(dbm.data_dir()) / "scans" / row["passport_scan"])

    @app.post("/mrz")
    def mrz_read():
        """Return MRZ data as JSON for the candidate form (from a pasted text or an uploaded scan)."""
        text = request.form.get("mrz_text", "").strip()
        try:
            if text:
                res = mrz.parse_mrz(text)
            else:
                upload = request.files.get("scan")
                if not upload or not upload.filename:
                    return jsonify(error="Изберете скан на паспорта или поставете двата MRZ реда."), 400
                suffix = Path(upload.filename).suffix.lower() or ".jpg"
                with tempfile.TemporaryDirectory() as tmp:
                    p = Path(tmp) / f"scan{suffix}"
                    upload.save(p)
                    res = mrz.read_mrz_from_file(p)
        except Exception as exc:  # OCR missing, unreadable image…
            return jsonify(error=str(exc)), 422
        country = dbm.find_country(get_db(), res.nationality)
        issuer = dbm.find_country(get_db(), res.issuing_country)
        return jsonify(
            valid=res.valid, warnings=res.warnings, raw=res.raw,
            fields={
                "name_lat": res.name_lat,
                "passport_no": res.passport_no,
                "gender": res.gender,
                "birth_date": _iso_to_bg(res.birth_date),
                "passport_expiry": _iso_to_bg(res.expiry_date),
                "citizenship_id": country["id"] if country else "",
                "passport_issued_by": (issuer["name_official"] or issuer["name"]) if issuer else "",
            },
            nationality=res.nationality,
        )

    # ------------------------------------------------------------ employers & positions
    @app.get("/employers")
    def employers():
        q = request.args.get("q", "").strip()
        sql = ("SELECT e.*, (SELECT count(*) FROM position p WHERE p.employer_id=e.id) AS npos,"
               " (SELECT count(*) FROM candidate ca WHERE ca.employer_id=e.id) AS nworkers,"
               " (SELECT count(*) FROM employer_address a WHERE a.employer_id=e.id) AS naddr FROM employer e")
        args = []
        if q:
            sql += " WHERE e.name LIKE ? OR e.eik LIKE ? OR e.rep_name LIKE ? OR CAST(e.ref_no AS TEXT)=?"
            args = [f"%{q}%"] * 3 + [q]
        rows = get_db().execute(sql + " ORDER BY e.name", args).fetchall()
        required = [f.name for f in forms.EMPLOYER if f.required]
        incomplete = {r["id"] for r in rows if not all((r[k] or "").strip() for k in required)}
        return render_template("employers.html", rows=rows, q=q, incomplete=incomplete)

    @app.route("/employers/new", methods=["GET", "POST"])
    @app.route("/employers/<int:eid>", methods=["GET", "POST"])
    def employer(eid=None):
        d = get_db()
        row = _one("SELECT * FROM employer WHERE id=?", eid) if eid else None
        values, errors = (dict(row) if row else {"rep_role": "управител"}), {}
        addresses = [r["address"] for r in d.execute(
            "SELECT address FROM employer_address WHERE employer_id=? ORDER BY sort_order, id", (eid or 0,))]
        if request.method == "POST":
            new_addresses = []
            for a in request.form.getlist("addresses"):
                a = re.sub(r"\s+", " ", a).strip()
                if a and a not in new_addresses:
                    new_addresses.append(a)
            try:
                data = forms.parse_form(forms.EMPLOYER, request.form)
                data["eik"] = re.sub(r"\s+", "", data["eik"])
                if row:
                    _update("employer", eid, data)
                else:
                    eid = _insert("employer", data)
                _save_addresses(eid, new_addresses)
                flash("Работодателят е записан.", "ok")
                return redirect(url_for("employer", eid=eid))
            except forms.FormError as exc:
                errors, values = exc.errors, {**values, **request.form.to_dict()}
                addresses = new_addresses
        positions = d.execute("SELECT * FROM position WHERE employer_id=? ORDER BY title", (eid or 0,)).fetchall()
        workers = d.execute("SELECT id, ref_no, name_cyr, name_lat, visa_type FROM candidate WHERE employer_id=?"
                            " ORDER BY name_cyr", (eid or 0,)).fetchall()
        return render_template("employer.html", row=row, values=values, errors=errors,
                               fields=forms.EMPLOYER, positions=positions, addresses=addresses, workers=workers,
                               attach_groups=dbm.EMPLOYER_ATTACHMENTS,
                               files=_attachments("employer", eid) if eid else {})

    def _save_addresses(eid, new_addresses):
        """Replace the employer's address list. Workers keep the text of the address they already have."""
        d = get_db()
        d.execute("DELETE FROM employer_address WHERE employer_id=?", (eid,))
        for i, a in enumerate(new_addresses):
            d.execute("INSERT INTO employer_address (employer_id, address, sort_order) VALUES (?,?,?)", (eid, a, i))
        d.commit()

    # ------------------------------------------------------------ attachments
    def _attachments(owner_type, owner_id):
        out = {}
        for a in get_db().execute("SELECT * FROM attachment WHERE owner_type=? AND owner_id=?"
                                  " ORDER BY uploaded_at, id", (owner_type, owner_id)):
            out.setdefault(a["category"], []).append(a)
        return out

    attach_categories = {"worker": dict(dbm.WORKER_ATTACHMENTS), "employer": dict(dbm.EMPLOYER_ATTACHMENTS)}
    owner_page = {"worker": ("candidate", "cid", "candidate"), "employer": ("employer", "eid", "employer")}

    @app.post("/attachments/<owner_type>/<int:owner_id>/<category>")
    def attachment_upload(owner_type, owner_id, category):
        if category not in attach_categories.get(owner_type, {}):
            abort(404)
        endpoint, arg, table = owner_page[owner_type]
        _one(f"SELECT id FROM {table} WHERE id=?", owner_id)
        files = [f for f in request.files.getlist("files") if f and f.filename]
        back = url_for(endpoint, **{arg: owner_id}) + "#attachments"
        if not files:
            flash("Изберете поне един файл.", "error")
            return redirect(back)
        d = get_db()
        folder = Path(dbm.data_dir()) / "attachments"
        for f in files:
            original = Path(f.filename.replace("\\", "/")).name[:200] or "файл"
            ext = re.sub(r"[^a-z0-9.]", "", Path(original).suffix.lower())[:10]
            stored = f"{owner_type}-{owner_id}-{datetime.now():%Y%m%d%H%M%S}-{secrets.token_hex(4)}{ext}"
            f.save(folder / stored)
            aid = d.execute("INSERT INTO attachment (owner_type, owner_id, category, stored_name, original_name)"
                            " VALUES (?,?,?,?,?)", (owner_type, owner_id, category, stored, original)).lastrowid
            auth.log("create", "attachment", aid, _owner_label(owner_type, owner_id),
                     attach_categories[owner_type][category], "", original)
        d.commit()
        flash(f"Качени файлове: {len(files)} в „{attach_categories[owner_type][category]}“.", "ok")
        return redirect(back)

    def _owner_label(owner_type, owner_id):
        table = "candidate" if owner_type == "worker" else "employer"
        row = get_db().execute(f"SELECT * FROM {table} WHERE id=?", (owner_id,)).fetchone()
        return auth.record_label(table, row)

    # ------------------------------------------------------------ deleting (super user only)
    @app.post("/candidates/<int:cid>/delete")
    @auth.super_required
    def candidate_delete(cid):
        """Deletes the worker, the worker's cases, generated documents and attachments. The change history
        and the status history keep the record."""
        d = get_db()
        row = _one("SELECT * FROM candidate WHERE id=?", cid)
        label = auth.record_label("candidate", row)
        for c in d.execute('SELECT id FROM "case" WHERE candidate_id=?', (cid,)).fetchall():
            for g_ in d.execute("SELECT folder FROM generation WHERE case_id=?", (c["id"],)).fetchall():
                shutil.rmtree(Path(dbm.data_dir()) / "generated" / g_["folder"], ignore_errors=True)
            d.execute('DELETE FROM "case" WHERE id=?', (c["id"],))
        for a in d.execute("SELECT * FROM attachment WHERE owner_type='worker' AND owner_id=?", (cid,)).fetchall():
            (Path(dbm.data_dir()) / "attachments" / a["stored_name"]).unlink(missing_ok=True)
        d.execute("DELETE FROM attachment WHERE owner_type='worker' AND owner_id=?", (cid,))
        d.execute("DELETE FROM candidate WHERE id=?", (cid,))
        auth.log("delete", "candidate", cid, label, "", json.dumps(dict(row), ensure_ascii=False, default=str), "")
        d.commit()
        flash(f"Работникът {label} е изтрит. Записът остава в историята на промените.", "ok")
        return redirect(url_for("candidates"))

    @app.post("/employers/<int:eid>/delete")
    @auth.super_required
    def employer_delete(eid):
        d = get_db()
        row = _one("SELECT * FROM employer WHERE id=?", eid)
        label = auth.record_label("employer", row)
        n = d.execute("SELECT count(*) FROM candidate WHERE employer_id=?", (eid,)).fetchone()[0]
        n += d.execute('SELECT count(*) FROM "case" WHERE employer_id=?', (eid,)).fetchone()[0]
        if n:
            flash("Работодателят не се изтрива, докато има работници или случаи при него. "
                  "Преместете или изтрийте първо тях.", "error")
            return redirect(url_for("employer", eid=eid))
        for a in d.execute("SELECT * FROM attachment WHERE owner_type='employer' AND owner_id=?", (eid,)).fetchall():
            (Path(dbm.data_dir()) / "attachments" / a["stored_name"]).unlink(missing_ok=True)
        d.execute("DELETE FROM attachment WHERE owner_type='employer' AND owner_id=?", (eid,))
        d.execute("DELETE FROM position WHERE employer_id=?", (eid,))
        d.execute("DELETE FROM employer WHERE id=?", (eid,))
        auth.log("delete", "employer", eid, label, "", json.dumps(dict(row), ensure_ascii=False, default=str), "")
        d.commit()
        flash(f"Работодателят {label} е изтрит. Записът остава в историята на промените.", "ok")
        return redirect(url_for("employers"))

    @app.get("/attachments/<int:aid>")
    def attachment_get(aid):
        a = _one("SELECT * FROM attachment WHERE id=?", aid)
        return send_file(Path(dbm.data_dir()) / "attachments" / a["stored_name"],
                         download_name=a["original_name"], as_attachment=request.args.get("dl") == "1")

    @app.post("/attachments/<int:aid>/delete")
    def attachment_delete(aid):
        a = _one("SELECT * FROM attachment WHERE id=?", aid)
        get_db().execute("DELETE FROM attachment WHERE id=?", (aid,))
        auth.log("delete", "attachment", aid, _owner_label(a["owner_type"], a["owner_id"]),
                 attach_categories.get(a["owner_type"], {}).get(a["category"], a["category"]), a["original_name"], "")
        get_db().commit()
        (Path(dbm.data_dir()) / "attachments" / a["stored_name"]).unlink(missing_ok=True)
        endpoint, arg, _ = owner_page[a["owner_type"]]
        flash(f"Файлът „{a['original_name']}“ е изтрит.", "ok")
        return redirect(url_for(endpoint, **{arg: a["owner_id"]}) + "#attachments")

    @app.route("/employers/<int:eid>/positions/new", methods=["GET", "POST"])
    @app.route("/positions/<int:pid>", methods=["GET", "POST"])
    def position(eid=None, pid=None):
        row = _one("SELECT * FROM position WHERE id=?", pid) if pid else None
        eid = row["employer_id"] if row else eid
        emp = _one("SELECT * FROM employer WHERE id=?", eid)
        values, errors = (dict(row) if row else {}), {}
        copy_from = request.args.get("copy", type=int)
        if not row and copy_from:
            src = _one("SELECT * FROM position WHERE id=?", copy_from)
            values = {k: src[k] for k in src.keys() if k not in ("id", "employer_id", "created_at", "updated_at")}
        if request.method == "POST":
            try:
                data = forms.parse_form(forms.POSITION, request.form)
                if row:
                    _update("position", pid, data)
                else:
                    pid = _insert("position", {**data, "employer_id": eid})
                flash("Длъжността е записана.", "ok")
                return redirect(url_for("position", pid=pid))
            except forms.FormError as exc:
                errors, values = exc.errors, {**values, **request.form.to_dict()}
        others = get_db().execute(
            "SELECT p.id, p.title, e.name AS employer FROM position p JOIN employer e ON e.id=p.employer_id"
            " WHERE p.obosnovka<>'' OR p.dh_duties<>'' ORDER BY p.title").fetchall()
        return render_template("position.html", row=row, emp=emp, values=values, errors=errors,
                               fields=forms.POSITION, others=others,
                               ai_on=ai_text.ai_available())

    @app.post("/employers/<int:eid>/positions/ai-draft")
    def position_ai_draft(eid):
        """Return a draft of the justification or the job description as JSON (fills the form, saves nothing)."""
        emp = dict(_one("SELECT * FROM employer WHERE id=?", eid))
        kind = request.form.get("kind", "")
        if kind not in ("obosnovka", "obosnovka_ext", "dh"):
            return jsonify(error="Непознат вид текст."), 400
        pos = {f.name: request.form.get(f.name, "") for f in forms.POSITION}
        d = ai_text.draft(kind, pos, emp, hint=request.form.get("ai_hint", ""),
                          recruitment_confirmed=request.form.get("ai_recruit") == "1")
        return jsonify(fields=d.fields, source=d.source, warnings=d.warnings)

    # ------------------------------------------------------------ cases
    @app.get("/cases")
    def cases():
        q = request.args.get("q", "").strip()
        sql = ('SELECT c.*, ca.name_cyr, ca.passport_no, e.name AS employer, p.title AS position,'
               ' ct.name AS ctype, (SELECT max(created_at) FROM generation g WHERE g.case_id=c.id) AS last_gen'
               ' FROM "case" c JOIN candidate ca ON ca.id=c.candidate_id JOIN employer e ON e.id=c.employer_id'
               " LEFT JOIN position p ON p.id=c.position_id JOIN case_type ct ON ct.id=c.case_type_id")
        args = []
        if q:
            sql += " WHERE ca.name_cyr LIKE ? OR ca.name_lat LIKE ? OR e.name LIKE ? OR ca.passport_no LIKE ?"
            args = [f"%{q}%"] * 4
        sql += " ORDER BY c.updated_at DESC LIMIT 500"
        return render_template("cases.html", rows=get_db().execute(sql, args).fetchall(), q=q)

    CASE_LINKS = ("candidate_id", "employer_id", "position_id", "case_type_id")

    @app.route("/cases/new", methods=["GET", "POST"])
    @app.route("/cases/<int:case_id>/edit", methods=["GET", "POST"])
    def case_edit(case_id=None):
        d = get_db()
        row = _one('SELECT * FROM "case" WHERE id=?', case_id) if case_id else None
        copy_id = request.args.get("copy", type=int)
        if row:
            values = dict(row)
        elif copy_id:
            src = _one('SELECT * FROM "case" WHERE id=?', copy_id)
            values = {k: src[k] for k in src.keys()
                      if k not in ("id", "created_at", "updated_at", "airtable_id", "reg_no", "reg_date",
                                   "contract_no", "status")}
            values["copied_from_id"] = copy_id
            values["candidate_id"] = request.args.get("candidate_id", type=int)
        else:
            values = {**CASE_DEFAULTS,
                      "candidate_id": request.args.get("candidate_id", type=int),
                      "employer_id": request.args.get("employer_id", type=int)}
            w = d.execute("SELECT employer_id, position_id, visa_type FROM candidate WHERE id=?",
                          (values["candidate_id"] or 0,)).fetchone()
            if w:  # the worker profile already knows the employer, position and visa type
                values["employer_id"] = values["employer_id"] or w["employer_id"]
                if values["employer_id"] == w["employer_id"]:
                    values["position_id"] = w["position_id"]
                ct = d.execute(
                    "SELECT id FROM case_type WHERE (?='Удължаване' AND is_extension=1)"
                    " OR (?<>'Удължаване' AND is_extension=0 AND residence_period=?)"
                    " ORDER BY sort_order LIMIT 1", (w["visa_type"],) * 3).fetchone()
                if ct and w["visa_type"]:
                    values["case_type_id"] = ct["id"]
        errors = {}
        if request.method == "POST":
            try:
                data = forms.parse_form(forms.CASE, request.form)
                links = {}
                for k in CASE_LINKS:
                    v = request.form.get(k, "").strip()
                    links[k] = int(v) if v.isdigit() else None
                missing = [lbl for k, lbl in (("candidate_id", "Кандидат"), ("employer_id", "Работодател"),
                                              ("case_type_id", "Вид случай")) if not links[k]]
                if missing:
                    raise forms.FormError({k: f"{m}: задължително поле" for k, m in zip(missing, missing)})
                if links["position_id"]:
                    p = d.execute("SELECT employer_id FROM position WHERE id=?", (links["position_id"],)).fetchone()
                    if not p or p["employer_id"] != links["employer_id"]:
                        raise forms.FormError({"position_id": "Длъжността не е на избрания работодател."})
                data.update(links)
                if row:
                    _update("case", case_id, data)
                else:
                    if copy_id:
                        data["copied_from_id"] = copy_id
                    case_id = _insert("case", data)
                flash("Случаят е записан.", "ok")
                return redirect(url_for("case_view", case_id=case_id))
            except forms.FormError as exc:
                errors, values = exc.errors, {**values, **request.form.to_dict()}
        return render_template(
            "case_edit.html", row=row, values=values, errors=errors, fields=forms.CASE, copy_id=copy_id,
            candidates=d.execute("SELECT id, name_cyr, name_lat, passport_no FROM candidate ORDER BY name_cyr").fetchall(),
            employers=d.execute("SELECT id, name FROM employer ORDER BY name").fetchall(),
            positions=d.execute("SELECT id, employer_id, title, nkpd FROM position ORDER BY title").fetchall(),
            case_types=d.execute("SELECT * FROM case_type ORDER BY sort_order, name").fetchall(),
        )

    @app.get("/cases/<int:case_id>")
    def case_view(case_id):
        d = get_db()
        c = _one('SELECT c.*, ca.name_cyr, ca.name_lat, e.name AS employer, p.title AS position, ct.name AS ctype'
                 ' FROM "case" c JOIN candidate ca ON ca.id=c.candidate_id JOIN employer e ON e.id=c.employer_id'
                 " LEFT JOIN position p ON p.id=c.position_id JOIN case_type ct ON ct.id=c.case_type_id"
                 " WHERE c.id=?", case_id)
        ctx = build_context(d, case_id)
        tpls = []
        for t in _templates_for_case_type(c["case_type_id"], _case_iso3(case_id)):
            used = set(filter(None, t["placeholders"].split(",")))
            miss = missing_fields(ctx, used)
            tpls.append({"t": t, "missing": [(k, PLACEHOLDERS[k][0]) for k in miss]})
        gens = d.execute("SELECT * FROM generation WHERE case_id=? ORDER BY created_at DESC, id DESC",
                         (case_id,)).fetchall()
        files = {g["id"]: d.execute("SELECT * FROM generated_file WHERE generation_id=? ORDER BY id",
                                    (g["id"],)).fetchall() for g in gens}
        return render_template("case_view.html", c=c, tpls=tpls, gens=gens, files=files,
                               pdf=render.converter_name())

    @app.post("/cases/<int:case_id>/delete")
    @auth.super_required
    def case_delete(case_id):
        _one('SELECT id FROM "case" WHERE id=?', case_id)
        if get_db().execute("SELECT 1 FROM generation WHERE case_id=?", (case_id,)).fetchone():
            flash("Случаят не се изтрива, защото има генерирани документи. Историята се пази.", "error")
            return redirect(url_for("case_view", case_id=case_id))
        get_db().execute('DELETE FROM "case" WHERE id=?', (case_id,))
        get_db().commit()
        flash("Случаят е изтрит.", "ok")
        return redirect(url_for("cases"))

    @app.post("/cases/<int:case_id>/generate")
    def case_generate(case_id):
        gen_id, errors = generate_case(case_id)
        if gen_id is None:
            flash(errors[0] if errors else "Нищо не е генерирано: няма бланки за този вид случай.", "error")
        elif errors:
            flash("Част от документите не са готови: " + "; ".join(errors), "error")
        else:
            flash("Документите са генерирани. Отворете ги по-долу, в „История на генерираните документи“.", "ok")
        return redirect(url_for("case_view", case_id=case_id))

    def generate_case(case_id):
        """Fill every active template of the case type, convert to PDF, keep it as a new history entry."""
        d = get_db()
        c = _one('SELECT c.*, ca.name_cyr FROM "case" c JOIN candidate ca ON ca.id=c.candidate_id WHERE c.id=?',
                 case_id)
        tpls = _templates_for_case_type(c["case_type_id"], _case_iso3(case_id))
        if not tpls:
            return None, ["Няма избрани бланки за този вид случай (Бланки → отметнете вида случай)."]
        ctx = build_context(d, case_id)
        stamp = datetime.now()
        rel = Path(str(case_id)) / f"{stamp:%Y-%m-%d_%H%M%S}"
        folder = Path(dbm.data_dir()) / "generated" / rel
        n = 1
        while folder.exists():
            n += 1
            rel = Path(str(case_id)) / f"{stamp:%Y-%m-%d_%H%M%S}-{n}"
            folder = Path(dbm.data_dir()) / "generated" / rel
        (folder / "docx").mkdir(parents=True)
        snapshot = {k: (list(v) if isinstance(v, list) else str(v) if not isinstance(v, bool) else v)
                    for k, v in flatten(ctx).items()}
        gen_id = d.execute("INSERT INTO generation (case_id, folder, snapshot) VALUES (?,?,?)",
                           (case_id, rel.as_posix(), json.dumps(snapshot, ensure_ascii=False))).lastrowid
        errors, made, used_names = [], [], set()
        for t in tpls:
            base = f"{_safe_name(t['name'])} - {_safe_name(c['name_cyr'])}"
            if base.lower() in used_names:  # two templates with the same (sanitised) name
                base = f"{base} ({t['id']})"
            used_names.add(base.lower())
            out = folder / "docx" / f"{base}.docx"
            try:
                render.fill_docx(_template_path(t), ctx, out)
                made.append((t, out))
            except Exception as exc:
                errors.append(f"{t['name']}: {exc}")
                d.execute("INSERT INTO generated_file (generation_id, template_name, error) VALUES (?,?,?)",
                          (gen_id, t["name"], str(exc)))
        pdfs = {}
        if made:
            try:
                pdfs = render.to_pdf([o for _, o in made], folder)  # may be partial
            except Exception as exc:
                errors.append(f"PDF: {exc}")
            missing = [t["name"] for t, o in made if o not in pdfs]
            if pdfs and missing:
                errors.append("няма PDF за: " + ", ".join(missing))
        for t, out in made:
            pdf = pdfs.get(out)
            d.execute("INSERT INTO generated_file (generation_id, template_name, pdf_name, docx_name, error)"
                      " VALUES (?,?,?,?,?)",
                      (gen_id, t["name"], pdf.name if pdf else "", f"docx/{out.name}",
                       "" if pdf else "няма PDF"))
        d.commit()
        return gen_id, errors

    app.generate_case = generate_case  # used by tests

    @app.get("/generated/<int:gen_id>/<path:name>")
    def generated_file(gen_id, name):
        g = _one("SELECT * FROM generation WHERE id=?", gen_id)
        allowed = {r["pdf_name"] for r in get_db().execute(
            "SELECT pdf_name, docx_name FROM generated_file WHERE generation_id=?", (gen_id,))}
        allowed |= {r["docx_name"] for r in get_db().execute(
            "SELECT docx_name FROM generated_file WHERE generation_id=?", (gen_id,))}
        if name not in allowed - {""}:
            abort(404)
        path = Path(dbm.data_dir()) / "generated" / g["folder"] / name
        return send_file(path, as_attachment=request.args.get("dl") == "1", download_name=Path(name).name)

    @app.get("/generated/<int:gen_id>.zip")
    def generated_zip(gen_id):
        g = _one("SELECT * FROM generation WHERE id=?", gen_id)
        base = Path(dbm.data_dir()) / "generated" / g["folder"]
        buf = io.BytesIO()
        col = "docx_name" if request.args.get("kind") == "docx" else "pdf_name"
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for r in get_db().execute(f"SELECT {col} FROM generated_file WHERE generation_id=? AND {col}<>''",
                                      (gen_id,)):
                z.write(base / r[col], Path(r[col]).name)
        buf.seek(0)
        kind = "word" if col == "docx_name" else "pdf"
        return send_file(buf, mimetype="application/zip", as_attachment=True,
                         download_name=f"dokumenti-{kind}-{g['case_id']}-{Path(g['folder']).name}.zip")

    # ------------------------------------------------------------ templates
    @app.get("/templates")
    def templates():
        d = get_db()
        rows = d.execute("SELECT * FROM doc_template ORDER BY is_active DESC, sort_order, name").fetchall()
        types = d.execute("SELECT * FROM case_type ORDER BY sort_order, name").fetchall()
        links = {(r["case_type_id"], r["template_id"]) for r in d.execute("SELECT * FROM case_type_template")}
        return render_template("templates.html", rows=rows, types=types, links=links)

    @app.post("/templates/upload")
    def template_upload():
        upload = request.files.get("file")
        name = request.form.get("name", "").strip()
        replace_id = request.form.get("replace_id", type=int)
        if not upload or not upload.filename:
            flash("Изберете Word файл (.docx).", "error")
            return redirect(url_for("templates"))
        if Path(upload.filename).suffix.lower() != ".docx":
            flash("Бланката трябва да е .docx. Стар .doc файл отворете в Word и запишете като .docx.", "error")
            return redirect(url_for("templates"))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "upload.docx"
            upload.save(p)
            check = render.check_template(p)
            if not check.ok:
                return render_template("template_check.html", check=check, filename=upload.filename,
                                       placeholders=PLACEHOLDERS), 422
            stem = secure_filename(Path(upload.filename).stem) or "blanka"
            fname = f"{datetime.now():%Y%m%d%H%M%S}-{secrets.token_hex(4)}-{stem}.docx"
            # exclusive create: never overwrite an existing template file
            with open(p, "rb") as src, open(Path(dbm.data_dir()) / "templates" / fname, "xb") as dst:
                shutil.copyfileobj(src, dst)
        d = get_db()
        if replace_id:
            old = _one("SELECT * FROM doc_template WHERE id=?", replace_id)
            # keep the old file on disk (history); point the record to the new one
            d.execute("UPDATE doc_template SET filename=?, placeholders=?, uploaded_at=datetime('now','localtime'),"
                      " name=? WHERE id=?", (fname, ",".join(sorted(check.used)), name or old["name"], replace_id))
            tid = replace_id
        else:
            tid = d.execute("INSERT INTO doc_template (name, filename, placeholders) VALUES (?,?,?)",
                            (name or Path(upload.filename).stem, fname, ",".join(sorted(check.used)))).lastrowid
            for ct in request.form.getlist("case_types"):
                d.execute("INSERT OR IGNORE INTO case_type_template VALUES (?,?)", (int(ct), tid))
        d.commit()
        flash(f"Бланката е качена. Намерени полета: {len(check.used)}.", "ok")
        return redirect(url_for("templates"))

    @app.post("/templates/<int:tid>/settings")
    def template_settings(tid):
        d = get_db()
        _one("SELECT id FROM doc_template WHERE id=?", tid)
        iso = lambda k: ",".join(sorted(_iso_set(request.form.get(k, ""))))  # noqa: E731
        d.execute("UPDATE doc_template SET name=?, is_active=?, sort_order=?, countries=?, exclude_countries=?"
                  " WHERE id=?",
                  (request.form.get("name", "").strip() or "Бланка", 1 if request.form.get("is_active") else 0,
                   request.form.get("sort_order", type=int) or 100, iso("countries"), iso("exclude_countries"), tid))
        d.execute("DELETE FROM case_type_template WHERE template_id=?", (tid,))
        for ct in request.form.getlist("case_types"):
            d.execute("INSERT OR IGNORE INTO case_type_template VALUES (?,?)", (int(ct), tid))
        d.commit()
        flash("Настройките на бланката са записани.", "ok")
        return redirect(url_for("templates"))

    @app.get("/templates/<int:tid>/download")
    def template_download(tid):
        t = _one("SELECT * FROM doc_template WHERE id=?", tid)
        return send_file(_template_path(t), as_attachment=True, download_name=f"{_safe_name(t['name'])}.docx")

    @app.get("/placeholders")
    def placeholders():
        return render_template("placeholders.html", placeholders=PLACEHOLDERS, list_fields=LIST_FIELDS)

    # ------------------------------------------------------------ case types & countries
    @app.route("/case-types", methods=["GET", "POST"])
    def case_types():
        d = get_db()
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if name:
                d.execute("INSERT INTO case_type (name, legal_ground, residence_period, is_extension, sort_order)"
                          " VALUES (?,?,?,?,?)",
                          (name, request.form.get("legal_ground", "").strip(),
                           request.form.get("residence_period", "").strip(),
                           1 if request.form.get("is_extension") else 0, 100))
                d.commit()
                flash("Видът случай е добавен.", "ok")
            return redirect(url_for("case_types"))
        return render_template("case_types.html",
                               rows=d.execute("SELECT * FROM case_type ORDER BY sort_order, name").fetchall())

    @app.post("/case-types/<int:ctid>")
    def case_type_save(ctid):
        _one("SELECT id FROM case_type WHERE id=?", ctid)
        _update("case_type", ctid, {
            "name": request.form.get("name", "").strip() or "Без име",
            "legal_ground": request.form.get("legal_ground", "").strip(),
            "residence_period": request.form.get("residence_period", "").strip(),
            "is_extension": 1 if request.form.get("is_extension") else 0,
        }, touch=False)
        flash("Видът случай е записан.", "ok")
        return redirect(url_for("case_types"))

    @app.route("/countries", methods=["GET", "POST"])
    def countries():
        if request.method == "POST":
            try:
                data = forms.parse_form(forms.COUNTRY, request.form)
                data["iso3"] = data["iso3"].upper() or None
                cid = request.form.get("id", type=int)
                if cid:
                    _update("country", cid, data, touch=False)
                else:
                    _insert("country", data)
                flash("Държавата е записана.", "ok")
            except forms.FormError as exc:
                flash(str(exc), "error")
            return redirect(url_for("countries"))
        return render_template("countries.html", rows=_countries(), fields=forms.COUNTRY)

    # ------------------------------------------------------------ import
    @app.route("/import", methods=["GET", "POST"])
    def import_page():
        from . import importer
        summary = None
        if request.method == "POST":
            upload = request.files.get("file")
            if not upload or not upload.filename.lower().endswith(".csv"):
                flash("Изберете CSV файл, свален от Airtable.", "error")
            else:
                with tempfile.TemporaryDirectory() as tmp:
                    p = Path(tmp) / "import.csv"
                    upload.save(p)
                    try:
                        records = importer.read_csv(p)
                        stats = importer.import_records(get_db(), records)
                        summary = f"Прочетени записи: {len(records)}\n" + stats.summary()
                    except (UnicodeDecodeError, Exception) as exc:  # bad encoding / not a CSV
                        get_db().rollback()
                        flash(f"Импортът не успя, нищо не е записано: {exc}", "error")
        return render_template("import.html", summary=summary)


def _iso_to_bg(iso):
    from .grammar import fmt_date
    return fmt_date(iso) if iso else ""
