"""Stage 5 of the задание: dashboard, calendar, status board, reports and e-mails."""
from datetime import date, datetime, timedelta
from pathlib import Path

from docautomate import mailer, reports
from docautomate.db import connect

from test_app import _setup_case


def _db(app):
    return connect(Path(app.config["DATABASE"]))


def _rows(**cols):
    base = {"status": "Нов", "status_changed_at": None, "created_at": "2026-01-01 08:00:00", "residence_until": None,
            "filed_date": None, "permit_date": None, "visa_interview_date": None, "visa_date": None,
            "arrival_date": None, "migration_reg_date": None, "lk_submit_date": None, "lk_pickup_date": None,
            "ref_no": 1, "name_cyr": "А"}
    return {**base, **cols}


def test_week_and_month_bounds():
    assert reports.week_bounds(date(2026, 11, 26)) == (date(2026, 11, 23), date(2026, 11, 29))
    assert reports.month_bounds(date(2026, 2, 10)) == (date(2026, 2, 1), date(2026, 2, 28))
    weeks = reports.calendar_weeks(date(2026, 11, 1), date(2026, 11, 30), [])
    assert weeks[0][0]["date"] == date(2026, 10, 26) and not weeks[0][0]["in_range"]
    assert all(len(w) == 7 for w in weeks)


def test_events_include_both_period_ends_and_filter_by_kind():
    rows = [_rows(arrival_date="2026-11-23", lk_pickup_date="2026-11-29", visa_interview_date="2026-11-30")]
    evs = reports.events(rows, date(2026, 11, 23), date(2026, 11, 29))
    assert [e["label"] for e in evs] == ["Пристигане", "Взимане на ЛК"]
    assert [e["label"] for e in reports.events(rows, date(2026, 11, 23), date(2026, 11, 29), ["arrival_date"])] \
        == ["Пристигане"]


def test_delay_report_red_first_then_days_over():
    today = date(2026, 11, 26)
    d = lambda n: (today - timedelta(days=n)).isoformat() + " 08:00:00"  # noqa: E731
    rows = [_rows(ref_no=1, status="Подаден Миграция", status_changed_at=d(45)),   # orange, 5 over
            _rows(ref_no=2, status="Подаден Миграция", status_changed_at=d(70)),   # red, 10 over
            _rows(ref_no=3, status="Готови документи", status_changed_at=d(20)),   # red, 6 over
            _rows(ref_no=4, status="Готови документи", status_changed_at=d(9)),    # orange, 2 over
            _rows(ref_no=5, status="Работещ", status_changed_at=d(400))]           # no colour
    out = reports.delayed(rows, today)
    assert [x["r"]["ref_no"] for x in out] == [2, 3, 1, 4]


def test_residence_groups_and_stage_medians():
    today = date(2026, 11, 26)
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    rows = [_rows(residence_until=d(n)) for n in (60, 61, 90, 91, 120, 121, -1)] + [_rows()]
    g = reports.residence(rows, today)
    assert (len(g["red"]), len(g["orange"]), len(g["yellow"]), len(g["expired"]), len(g["none"])) == (1, 2, 2, 1, 1)
    st = reports.stage_times([_rows(filed_date="2026-01-01", permit_date="2026-01-11"),
                              _rows(filed_date="2026-01-01", permit_date="2026-01-31"),
                              _rows(filed_date="2026-02-01", permit_date="2026-01-01")])  # wrong order: skipped
    assert st["permit"] == {"median": 20.0, "count": 2} and st["visa"]["count"] == 0


def test_dashboard_board_reports_render_with_data(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    monday, _ = reports.week_bounds(date.today())
    c = _db(app)
    c.execute("UPDATE candidate SET status='Подаден Миграция', status_changed_at=?, arrival_date=?,"
              " residence_until=? WHERE id=?",
              ((date.today() - timedelta(days=70)).isoformat(), monday.isoformat(),
               (date.today() + timedelta(days=30)).isoformat(), cid))
    c.commit()
    html = client.get("/").data.decode()
    assert "Управленско табло" in html and "cal-card ev-arrival_date" in html and "Testova Anna" not in html
    assert "1</b><span>забавяния" in html and "Тестова Анна" in html
    assert "cal-card" not in client.get("/?kind=lk_pickup_date").data.decode()
    assert "cal month" in client.get("/?view=month").data.decode()
    html = client.get("/board").data.decode()
    assert "board-card delay-red" in html
    html = client.get("/reports").data.decode()
    assert "Забавяне по статус" in html and "Тестова Анна" in html and "Изтичащо пребиваване" in html
    html = client.get(f"/reports?employer_report={eid}").data.decode()
    assert "ТЕСТ ЕООД" in html and "Печат / PDF" in html
    # a custom period replaces the week
    html = client.get("/?from=01.01.2020&to=02.01.2020").data.decode()
    assert "01.01.2020 – 02.01.2020" in html


def test_mail_schedule_and_send(client, app, monkeypatch):
    c = _db(app)
    assert not mailer.configured(c)
    assert mailer.due(c, datetime(2026, 11, 30, 7, 0)) == []  # before the hour
    client.post("/settings/mail", data={"smtp_host": "smtp.example.com", "smtp_port": "465", "smtp_security": "ssl",
                                        "smtp_user": "u", "smtp_password": "secret", "mail_from": "office@example.com",
                                        "mail_extra": "boss@example.com", "send_hour": "8",
                                        "base_url": "http://x"})
    s = mailer.settings(c)
    assert s["smtp_password"] == "secret"
    client.post("/settings/mail", data={"smtp_password": "", "smtp_host": "smtp.example.com"})
    assert mailer.settings(c)["smtp_password"] == "secret"  # empty keeps the stored password
    assert mailer.configured(c)
    # Monday 30.11.2026 at 08:00 → daily + weekly; 1 December → daily + monthly
    assert [k for k, _ in mailer.due(c, datetime(2026, 11, 30, 8, 0))] == ["delays", "movement"]
    assert [k for k, _ in mailer.due(c, datetime(2026, 12, 1, 9, 0))] == ["delays", "residence"]

    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, context=None):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, pw):
            sent.append(("login", user))

        def send_message(self, msg):
            sent.append(("send", msg["Subject"], msg["To"]))
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    with app.app_context():
        ok, err = mailer.send(c, "delays", "2026-11-30")
    assert ok and err == ""
    assert sent[0] == ("connect", "smtp.example.com", 465) and sent[-1][0] == "send"
    assert "boss@example.com" in sent[-1][2] and sent[-1][1].startswith("Забавяне по статус: 0 червени")
    # sent once per period
    assert [k for k, _ in mailer.due(c, datetime(2026, 11, 30, 10, 0))] == ["movement"]
    with app.app_context():
        for kind in ("movement", "residence"):
            assert mailer.send(c, kind, "p")[0]


def test_failed_send_is_logged_not_raised(client, app, monkeypatch):
    c = _db(app)
    mailer.save_settings(c, {"smtp_host": "h", "mail_from": "a@b.c", "mail_extra": "x@y.z"})

    def boom(*a, **k):
        raise OSError("няма връзка")
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", boom)
    with app.app_context():
        ok, err = mailer.send(c, "delays", "2026-11-30")
    assert not ok and "няма връзка" in err
    assert c.execute("SELECT ok FROM mail_log").fetchone()[0] == 0
    assert [k for k, _ in mailer.due(c, datetime(2026, 11, 30, 9, 0))][0] == "delays"  # retried later


def test_mail_settings_can_come_from_env_and_the_screen_wins(client, app, monkeypatch):
    c = _db(app)
    for k, v in {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "office@example.com", "SMTP_PASSWORD": "pw",
                 "MAIL_FROM": "office@example.com", "MAIL_TO": "office@example.com"}.items():
        monkeypatch.setenv("DOCAUTOMATE_" + k, v)
    s = mailer.settings(c)
    assert (s["smtp_host"], s["mail_from"], s["smtp_password"], s["smtp_port"]) == \
        ("smtp.example.com", "office@example.com", "pw", "465")
    assert mailer.recipients(c) == ["office@example.com"] and mailer.configured(c)
    html = client.get("/settings/mail").data.decode()
    assert "office@example.com" in html and 'value="pw"' not in html  # the password is never shown
    mailer.save_settings(c, {"mail_from": "other@example.com", "smtp_host": ""})
    s = mailer.settings(c)
    assert s["mail_from"] == "other@example.com" and s["smtp_host"] == "smtp.example.com"  # empty on screen = .env
