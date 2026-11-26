"""Управленско табло, календар, изглед по статуси и рапорти (задание 08, 09)."""
from __future__ import annotations

from datetime import date, timedelta

from flask import flash, redirect, render_template, request, url_for

from . import auth, mailer, render, reports
from . import schedule as sched
from .db import get_db

MONTHS_BG = ("", "януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври",
             "ноември", "декември")
DAYS_BG = ("пон", "вто", "сря", "чет", "пет", "съб", "нед")


def _filters():
    a = request.args
    return {
        "employers": [int(x) for x in a.getlist("employer") if x.isdigit()],
        "visa": a.get("visa", "").strip(),
        "status": a.get("status", "").strip(),
        "assigned": a.get("assigned", "").strip(),
    }


def _choices():
    d = get_db()
    return {"employers": d.execute("SELECT id, name FROM employer ORDER BY name").fetchall(),
            "statuses": sched.ALL_STATUSES, "users": auth.active_users(), "event_kinds": reports.EVENTS,
            "MONTHS_BG": MONTHS_BG, "DAYS_BG": DAYS_BG}


def register(app):
    @app.get("/")
    def home():
        """Управленско табло: current delays, workers by status, residence expiring, events of the period,
        and the calendar. Period defaults to this week Monday-Sunday; both dates included."""
        today = date.today()
        f = _filters()
        rows = reports.workers(get_db(), f)
        view = request.args.get("view", "week")
        anchor = reports.parse_day(request.args.get("at"), today)
        if request.args.get("from") or request.args.get("to"):
            start = reports.parse_day(request.args.get("from"), reports.week_bounds(today)[0])
            end = reports.parse_day(request.args.get("to"), start + timedelta(days=6))
            if end < start:
                start, end = end, start
        elif view == "month":
            start, end = reports.month_bounds(anchor)
        else:
            start, end = reports.week_bounds(anchor)
        kinds = [k for k in request.args.getlist("kind") if k in reports.EVENT_LABEL]
        evs = reports.events(rows, start, end, kinds or None)
        if view == "month":
            prev_at, next_at = (start - timedelta(days=1)).replace(day=1), end + timedelta(days=1)
        else:
            prev_at, next_at = start - timedelta(days=7), start + timedelta(days=7)
        return render_template(
            "dashboard.html", f=f, rows=rows, today=today, start=start, end=end, view=view, kinds=kinds,
            delayed=reports.delayed(rows, today), status_counts=reports.by_status(rows),
            residence=reports.residence(rows, today), events=evs,
            event_counts={k: sum(1 for e in evs if e["field"] == k) for k, _ in reports.EVENTS},
            weeks=reports.calendar_weeks(start, end, evs), prev_at=prev_at, next_at=next_at,
            custom=bool(request.args.get("from") or request.args.get("to")), pdf=render.converter_name(),
            **_choices())

    @app.get("/board")
    def board():
        """Изглед по статуси: a column per status, cards with number, employer, Assigned and delay colour."""
        rows = reports.workers(get_db(), _filters())
        cols = {s: [] for s in sched.ALL_STATUSES}
        for r in rows:
            cols.setdefault(r["status"], []).append({"r": r, **sched.addition_info(r)})
        cols = {s: v for s, v in cols.items() if v or s in sched.STATUSES}
        return render_template("board.html", cols=cols, f=_filters(), **_choices())

    @app.get("/reports")
    def reports_page():
        """The periodic reports as pages (the e-mails send the same content) plus the on-demand ones."""
        d = get_db()
        today = date.today()
        rows = reports.workers(d, _filters())
        eid = request.args.get("employer_report", type=int)
        emp_rows = []
        emp = None
        if eid:
            emp = d.execute("SELECT * FROM employer WHERE id=?", (eid,)).fetchone()
            emp_rows = reports.workers(d, {"employers": [eid]})
        return render_template(
            "reports.html", f=_filters(), today=today, delayed=reports.delayed(rows, today),
            movement=reports.movement(rows, today), residence=reports.residence(rows, today),
            stage=reports.stage_times(rows), emp=emp, emp_rows=emp_rows,
            mail_ready=mailer.configured(d), **_choices())

    @app.route("/settings/mail", methods=["GET", "POST"])
    @auth.super_required
    def mail_settings():
        d = get_db()
        if request.method == "POST":
            mailer.save_settings(d, request.form.to_dict())
            if request.form.get("test"):
                ok, err = mailer.send(d, "delays", date.today().isoformat(), log_kind="test")
                flash("Тестовият рапорт е изпратен." if ok else f"Изпращането не успя: {err}", "ok" if ok else "error")
            else:
                flash("Настройките са записани.", "ok")
            return redirect(url_for("mail_settings"))
        return render_template("mail_settings.html", s=mailer.settings(d), fields=mailer.FIELDS,
                               to=mailer.recipients(d), ready=mailer.configured(d),
                               log=d.execute("SELECT * FROM mail_log ORDER BY id DESC LIMIT 20").fetchall())
