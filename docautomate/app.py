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
                   send_file, url_for)
from werkzeug.utils import secure_filename

from . import db as dbm
from . import forms, mrz, render
from .context import LIST_FIELDS, PLACEHOLDERS, build_context, flatten, missing_fields
from .db import get_db

ROOT = Path(__file__).resolve().parent.parent
MASTERS_DIR = ROOT / "masters"


def default_data_dir() -> Path:
    return Path(os.environ.get("DOCAUTOMATE_DATA", ROOT / "data"))


def create_app(data_dir: Path | None = None, testing: bool = False) -> Flask:
    app = Flask(__name__)
    data_dir = Path(data_dir or default_data_dir())
    for sub in ("templates", "generated", "scans"):
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
    install_masters(conn, data_dir / "templates")
    conn.close()
    app.teardown_appcontext(dbm.close_db)
    _register(app)
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
    for i, item in enumerate(json.loads(manifest.read_text(encoding="utf-8"))):
        fname = item["file"]
        if conn.execute("SELECT 1 FROM doc_template WHERE filename=?", (fname,)).fetchone():
            continue
        src = MASTERS_DIR / fname
        if not src.exists():
            continue
        shutil.copy2(src, templates_dir / fname)
        check = render.check_template(src)
        tid = conn.execute(
            "INSERT INTO doc_template (name, filename, is_master, sort_order, placeholders) VALUES (?,?,?,?,?)",
            (item["name"], fname, 1, (i + 1) * 10, ",".join(sorted(check.used))),
        ).lastrowid
        for ct_name in item.get("case_types", []):
            ct = conn.execute("SELECT id FROM case_type WHERE name=?", (ct_name,)).fetchone()
            if ct:
                conn.execute("INSERT OR IGNORE INTO case_type_template VALUES (?,?)", (ct["id"], tid))
    conn.commit()


# ---------------------------------------------------------------- helpers

def _one(sql, *args):
    row = get_db().execute(sql, args).fetchone()
    if row is None:
        abort(404)
    return row


def _insert(table, values: dict) -> int:
    cols = ", ".join(values)
    q = ", ".join("?" * len(values))
    cur = get_db().execute(f'INSERT INTO "{table}" ({cols}) VALUES ({q})', list(values.values()))
    get_db().commit()
    return cur.lastrowid


def _update(table, row_id, values: dict, touch=True) -> None:
    sets = ", ".join(f"{k}=?" for k in values)
    if touch:
        sets += ", updated_at=datetime('now','localtime')"
    get_db().execute(f'UPDATE "{table}" SET {sets} WHERE id=?', [*values.values(), row_id])
    get_db().commit()


def _countries():
    return get_db().execute("SELECT * FROM country ORDER BY name").fetchall()


def _safe_name(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n]+', " ", text or "").strip()
    return re.sub(r"\s+", " ", text)[:80] or "документ"


def _templates_for_case_type(case_type_id):
    return get_db().execute(
        "SELECT t.* FROM doc_template t JOIN case_type_template ct ON ct.template_id=t.id"
        " WHERE ct.case_type_id=? AND t.is_active=1 ORDER BY t.sort_order, t.name",
        (case_type_id,),
    ).fetchall()


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
        return {"GENDER": dict(forms.GENDER), "now": datetime.now()}

    @app.template_filter("bgdate")
    def _bgdate(v):
        from .grammar import fmt_date
        return fmt_date(v)

    @app.errorhandler(sqlite3.IntegrityError)
    def _integrity(exc):
        flash(_integrity_message(exc), "error")
        return redirect(request.referrer or url_for("home"))

    # ------------------------------------------------------------ home
    @app.get("/")
    def home():
        d = get_db()
        counts = {t: d.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                  for t in ("candidate", "employer", "position", "case", "generation")}
        recent = d.execute(
            'SELECT c.id, c.updated_at, ca.name_cyr, e.name AS employer, ct.name AS ctype FROM "case" c'
            " JOIN candidate ca ON ca.id=c.candidate_id JOIN employer e ON e.id=c.employer_id"
            " JOIN case_type ct ON ct.id=c.case_type_id ORDER BY c.updated_at DESC LIMIT 10").fetchall()
        return render_template("home.html", counts=counts, recent=recent,
                               pdf=render.converter_name(), ocr=mrz.ocr_available())

    # ------------------------------------------------------------ candidates
    @app.get("/candidates")
    def candidates():
        q = request.args.get("q", "").strip()
        sql = ("SELECT ca.*, co.name AS citizenship FROM candidate ca"
               " LEFT JOIN country co ON co.id=ca.citizenship_id")
        args = []
        if q:
            sql += (" WHERE ca.name_cyr LIKE ? OR ca.name_lat LIKE ? OR ca.passport_no LIKE ?"
                    " OR ca.phone LIKE ?")
            args = [f"%{q}%"] * 4
        sql += " ORDER BY ca.updated_at DESC LIMIT 500"
        return render_template("candidates.html", rows=get_db().execute(sql, args).fetchall(), q=q)

    @app.route("/candidates/new", methods=["GET", "POST"])
    @app.route("/candidates/<int:cid>", methods=["GET", "POST"])
    def candidate(cid=None):
        row = _one("SELECT * FROM candidate WHERE id=?", cid) if cid else None
        values = dict(row) if row else {}
        errors = {}
        if request.method == "POST":
            try:
                data = forms.parse_form(forms.CANDIDATE, request.form)
                if row:
                    _update("candidate", cid, data)
                else:
                    cid = _insert("candidate", data)
                scan = request.files.get("passport_scan")
                if scan and scan.filename:
                    _save_scan(cid, scan)
                flash("Кандидатът е записан.", "ok")
                return redirect(url_for("candidate", cid=cid))
            except forms.FormError as exc:
                errors = exc.errors
                values = {**values, **request.form.to_dict()}
        cases = get_db().execute(
            'SELECT c.*, e.name AS employer, ct.name AS ctype FROM "case" c JOIN employer e ON e.id=c.employer_id'
            " JOIN case_type ct ON ct.id=c.case_type_id WHERE c.candidate_id=? ORDER BY c.created_at DESC",
            (cid or 0,)).fetchall()
        return render_template("candidate.html", row=row, values=values, errors=errors,
                               fields=forms.CANDIDATE, countries=_countries(), cases=cases,
                               ocr=mrz.ocr_available())

    def _save_scan(cid, upload):
        ext = Path(upload.filename).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".pdf", ".tif", ".tiff", ".bmp", ".webp"):
            flash("Сканът трябва да е снимка или PDF.", "error")
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
        rows = get_db().execute(
            "SELECT e.*, (SELECT count(*) FROM position p WHERE p.employer_id=e.id) AS npos,"
            ' (SELECT count(*) FROM "case" c WHERE c.employer_id=e.id) AS ncases'
            " FROM employer e ORDER BY e.name").fetchall()
        return render_template("employers.html", rows=rows)

    @app.route("/employers/new", methods=["GET", "POST"])
    @app.route("/employers/<int:eid>", methods=["GET", "POST"])
    def employer(eid=None):
        row = _one("SELECT * FROM employer WHERE id=?", eid) if eid else None
        values, errors = (dict(row) if row else {"rep_role": "управител"}), {}
        if request.method == "POST":
            try:
                data = forms.parse_form(forms.EMPLOYER, request.form)
                data["eik"] = re.sub(r"\s+", "", data["eik"])
                if row:
                    _update("employer", eid, data)
                else:
                    eid = _insert("employer", data)
                flash("Работодателят е записан.", "ok")
                return redirect(url_for("employer", eid=eid))
            except forms.FormError as exc:
                errors, values = exc.errors, {**values, **request.form.to_dict()}
        positions = get_db().execute("SELECT * FROM position WHERE employer_id=? ORDER BY title",
                                     (eid or 0,)).fetchall()
        return render_template("employer.html", row=row, values=values, errors=errors,
                               fields=forms.EMPLOYER, positions=positions)

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
                               fields=forms.POSITION, others=others)

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
            values = {"contract_months": 36, "probation_months": 6, "currency": "евро", "pay_day": "30",
                      "leave_days": 20, "extra_leave_days": 0, "notice_months": 3,
                      "working_time": "пълно работно време по график на смени при условията на сумирано "
                                      "изчисляване на работното време /СИРВ/",
                      "doc_city": "София",
                      "candidate_id": request.args.get("candidate_id", type=int),
                      "employer_id": request.args.get("employer_id", type=int)}
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
        for t in _templates_for_case_type(c["case_type_id"]):
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
    def case_delete(case_id):
        _one('SELECT id FROM "case" WHERE id=?', case_id)
        if get_db().execute("SELECT 1 FROM generation WHERE case_id=?", (case_id,)).fetchone():
            flash("Случаят има генерирани документи и не се изтрива (историята се пази).", "error")
            return redirect(url_for("case_view", case_id=case_id))
        get_db().execute('DELETE FROM "case" WHERE id=?', (case_id,))
        get_db().commit()
        flash("Случаят е изтрит.", "ok")
        return redirect(url_for("cases"))

    @app.post("/cases/<int:case_id>/generate")
    def case_generate(case_id):
        gen_id, errors = generate_case(case_id)
        if gen_id is None:
            flash(errors[0] if errors else "Няма бланки за този вид случай.", "error")
        elif errors:
            flash("Генерирано с грешки: " + "; ".join(errors), "error")
        else:
            flash("Документите са генерирани.", "ok")
        return redirect(url_for("case_view", case_id=case_id))

    def generate_case(case_id):
        """Fill every active template of the case type, convert to PDF, keep it as a new history entry."""
        d = get_db()
        c = _one('SELECT c.*, ca.name_cyr FROM "case" c JOIN candidate ca ON ca.id=c.candidate_id WHERE c.id=?',
                 case_id)
        tpls = _templates_for_case_type(c["case_type_id"])
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
        errors, made = [], []
        for t in tpls:
            out = folder / "docx" / f"{_safe_name(t['name'])} - {_safe_name(c['name_cyr'])}.docx"
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
                pdfs = render.to_pdf([o for _, o in made], folder)
            except Exception as exc:
                errors.append(f"PDF: {exc}")
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
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for r in get_db().execute("SELECT pdf_name FROM generated_file WHERE generation_id=? AND pdf_name<>''",
                                      (gen_id,)):
                z.write(base / r["pdf_name"], r["pdf_name"])
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True,
                         download_name=f"sluchai-{g['case_id']}-{Path(g['folder']).name}.zip")

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
            fname = f"{datetime.now():%Y%m%d%H%M%S}-{stem}.docx"
            shutil.copy2(p, Path(dbm.data_dir()) / "templates" / fname)
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
        d.execute("UPDATE doc_template SET name=?, is_active=?, sort_order=? WHERE id=?",
                  (request.form.get("name", "").strip() or "Бланка", 1 if request.form.get("is_active") else 0,
                   request.form.get("sort_order", type=int) or 100, tid))
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
        flash("Записано.", "ok")
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
