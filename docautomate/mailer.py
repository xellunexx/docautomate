"""E-mail reports to the super users (задание 07, 09): daily delays, Monday movement, residence on the 1st.

Nothing is sent until a mailbox is set in Настройки → Имейл рапорти. The send time is local time of this
computer (the office PC runs on Bulgarian time). Each report is sent once per day/week/month; the log
keeps what was sent and any error.
"""
from __future__ import annotations

import smtplib
import ssl
import threading
import time
from datetime import date, datetime
from email.message import EmailMessage

from flask import render_template

from . import reports

SCHEMA = """
CREATE TABLE IF NOT EXISTS setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS mail_log (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,                    -- delays | movement | residence | test
    period TEXT NOT NULL,                  -- 2026-11-27 / 2026-W48 / 2026-12
    sent_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    recipients TEXT NOT NULL DEFAULT '',
    ok INTEGER NOT NULL DEFAULT 1,
    error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_mail_log_kind ON mail_log(kind, period);
"""

FIELDS = (
    ("smtp_host", "Сървър за изпращане (SMTP)", "напр. smtp.gmail.com"),
    ("smtp_port", "Порт", "465 за SSL, 587 за STARTTLS"),
    ("smtp_security", "Защита", "ssl или starttls"),
    ("smtp_user", "Потребител", "обикновено целият имейл адрес"),
    ("smtp_password", "Парола", "за Gmail: „парола за приложение“"),
    ("mail_from", "От адрес", "адресът, от който излизат рапортите"),
    ("mail_extra", "Допълнителни получатели", "със запетая; супер юзърите с имейл получават винаги"),
    ("send_hour", "Час на изпращане", "0–23, българско време"),
    ("base_url", "Адрес на програмата за линковете", "напр. http://127.0.0.1:5000 или Cloudflare линка"),
)
DEFAULTS = {"smtp_port": "465", "smtp_security": "ssl", "send_hour": "8", "base_url": "http://127.0.0.1:5000"}


def init(conn) -> None:
    conn.executescript(SCHEMA)


def settings(conn) -> dict:
    out = dict(DEFAULTS)
    out.update({r[0]: r[1] for r in conn.execute("SELECT key, value FROM setting")})
    return out


def save_settings(conn, values: dict) -> None:
    for k, _, _ in FIELDS:
        if k in values:
            if k == "smtp_password" and not values[k]:
                continue  # empty = keep the stored password
            conn.execute("INSERT INTO setting (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (k, str(values[k]).strip()))
    conn.commit()


def recipients(conn) -> list[str]:
    s = settings(conn)
    out = [r[0] for r in conn.execute("SELECT email FROM app_user WHERE is_super=1 AND is_active=1 AND email<>''")]
    out += [x.strip() for x in s.get("mail_extra", "").split(",") if x.strip()]
    return list(dict.fromkeys(out))


def configured(conn) -> bool:
    s = settings(conn)
    return bool(s.get("smtp_host") and s.get("mail_from") and recipients(conn))


def build(conn, kind: str, today: date | None = None) -> tuple[str, str]:
    """(subject, html) of one report."""
    today = today or date.today()
    rows = reports.workers(conn)
    base = settings(conn).get("base_url", "").rstrip("/")
    if kind == "delays":
        items = reports.delayed(rows, today)
        red = sum(1 for x in items if x["delay"] == "red")
        subject = f"Забавяне по статус: {red} червени, {len(items) - red} оранжеви ({today:%d.%m.%Y})"
        html = render_template("mail_delays.html", items=items, base=base, today=today)
    elif kind == "movement":
        m = reports.movement(rows, today)
        subject = f"Движение за седмицата {m['last'][0]:%d.%m} – {m['last'][1]:%d.%m.%Y}"
        html = render_template("mail_movement.html", m=m, base=base)
    elif kind == "residence":
        g = reports.residence(rows, today)
        subject = (f"Изтичащо пребиваване: {len(g['red'])} червени, {len(g['orange'])} оранжеви,"
                   f" {len(g['yellow'])} жълти ({today:%m.%Y})")
        html = render_template("mail_residence.html", g=g, base=base)
    else:
        raise ValueError(kind)
    return subject, html


def send(conn, kind: str, period: str, today: date | None = None, log_kind: str | None = None) -> tuple[bool, str]:
    s = settings(conn)
    to = recipients(conn)
    if not configured(conn):
        return False, "Няма настроена поща или получател."
    subject, html = build(conn, kind, today)
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, s["mail_from"], ", ".join(to)
    msg.set_content("Отворете писмото в програма за поща, която показва HTML.")
    msg.add_alternative(html, subtype="html")
    ok, error = True, ""
    try:
        port = int(s.get("smtp_port") or 465)
        if s.get("smtp_security") == "starttls":
            with smtplib.SMTP(s["smtp_host"], port, timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if s.get("smtp_user"):
                    smtp.login(s["smtp_user"], s.get("smtp_password", ""))
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(s["smtp_host"], port, timeout=30, context=ssl.create_default_context()) as smtp:
                if s.get("smtp_user"):
                    smtp.login(s["smtp_user"], s.get("smtp_password", ""))
                smtp.send_message(msg)
    except Exception as exc:  # network, login, refused recipient…
        ok, error = False, str(exc)[:500]
    conn.execute("INSERT INTO mail_log (kind, period, recipients, ok, error) VALUES (?,?,?,?,?)",
                 (log_kind or kind, period, ", ".join(to), 1 if ok else 0, error))
    conn.commit()
    return ok, error


def due(conn, now: datetime) -> list[tuple[str, str]]:
    """Reports whose time has come and that were not sent successfully for their period yet."""
    try:
        hour = int(settings(conn).get("send_hour") or 8)
    except ValueError:
        hour = 8
    if now.hour < hour:
        return []
    todo = [("delays", now.strftime("%Y-%m-%d"))]
    if now.weekday() == 0:
        todo.append(("movement", now.strftime("%G-W%V")))
    if now.day == 1:
        todo.append(("residence", now.strftime("%Y-%m")))
    return [(k, p) for k, p in todo
            if not conn.execute("SELECT 1 FROM mail_log WHERE kind=? AND period=? AND ok=1", (k, p)).fetchone()]


def start_scheduler(app, connect, interval=60) -> threading.Thread:
    """Background check once a minute while the program runs. A failed send is retried next hour."""
    def loop():
        last_try = {}
        while True:
            try:
                with app.app_context(), app.test_request_context():
                    conn = connect()
                    try:
                        if configured(conn):
                            now = datetime.now()
                            for kind, period in due(conn, now):
                                key = (kind, period)
                                if last_try.get(key) and (time.time() - last_try[key]) < 3600:
                                    continue
                                last_try[key] = time.time()
                                send(conn, kind, period, now.date())
                    finally:
                        conn.close()
            except Exception:  # never let the scheduler kill the program
                pass
            time.sleep(interval)
    t = threading.Thread(target=loop, name="mail-reports", daemon=True)
    t.start()
    return t
