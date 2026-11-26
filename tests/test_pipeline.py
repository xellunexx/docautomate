"""Pipeline: „Следваща стъпка“ moves a worker along the path of the visa type after the checks."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from docautomate import pipeline, render
from docautomate import schedule as sched
from docautomate.db import connect

from test_app import _employer, _id_from

TODAY = date(2026, 11, 26)


@pytest.fixture(autouse=True)
def no_pdf(monkeypatch):
    monkeypatch.setattr(render, "to_pdf", lambda files, outdir: {})


def test_paths_per_visa_type():
    assert pipeline.path_for("3 години") == sched.STATUSES
    assert "Подаден Миграция" not in pipeline.path_for("3 месеца") and "Подаден АЗ" in pipeline.path_for("3 месеца")
    ext = pipeline.path_for("Удължаване")
    assert ext[0] == "Нов" and ext[-1] == "Работещ" and "Интервю за виза" not in ext
    assert pipeline.next_status("Нов", "Удължаване") == "Готови документи"
    assert pipeline.next_status("Работещ", "3 години") is None
    assert pipeline.next_status("Отказ", "3 години") is None


def _w(**kw):
    base = {"status": "Нов", "visa_type": "3 години", "employer_id": 1, "position_id": 1,
            "created_at": "2026-11-26 10:00:00", "status_changed_at": None}
    return {**base, **kw}


def test_hard_checks_block_and_soft_only_warn():
    st = pipeline.plan_step(_w(position_id=None), attachments=set(), doc_plan=None, position=None, today=TODAY)
    assert st.next == "Изпратен легализация" and st.blocked
    st = pipeline.plan_step(_w(), attachments=set(), doc_plan=None, position=None, today=TODAY)
    assert not st.blocked and [c.text for c in st.warnings] == ["Прикачен файл: Паспорт и свидетелство за съдимост"]


def test_documents_step_needs_texts_and_generates():
    w = _w(status="Изпратен легализация")
    plan = {"error": "", "templates": [{"t": {"name": "Заявление"}, "missing": [("x", "Заплата")]}]}
    st = pipeline.plan_step(w, attachments=set(), doc_plan=plan, position={"obosnovka": "", "dh_duties": ""},
                            today=TODAY)
    assert st.next == "Готови документи" and st.generate and st.blocked
    st = pipeline.plan_step(w, attachments=set(), doc_plan=plan, position={"obosnovka": "Текст", "dh_duties": "А"},
                            today=TODAY)
    assert not st.blocked and any("Заплата" in c.text for c in st.warnings)  # blanks are allowed, as „……“


def test_extension_uses_extension_text_and_three_months_needs_no_justification():
    pos = {"obosnovka": "", "obosnovka_ext": "Удължаване текст", "dh_duties": "А"}
    st = pipeline.plan_step(_w(visa_type="Удължаване"), attachments=set(), doc_plan=None, position=pos, today=TODAY)
    assert st.next == "Готови документи" and not st.blocked
    st = pipeline.plan_step(_w(visa_type="3 месеца", status="Изпратен легализация"), attachments=set(),
                            doc_plan=None, position={"obosnovka": "", "dh_duties": "А"}, today=TODAY)
    assert not st.blocked


def test_first_filing_needs_number_and_date_for_every_path():
    for visa, status, nxt in (("3 години", "Готови документи", "Подаден Миграция"),
                              ("3 месеца", "Готови документи", "Подаден АЗ")):
        st = pipeline.plan_step(_w(visa_type=visa, status=status), attachments=set(), doc_plan=None, position=None,
                                today=TODAY)
        assert st.next == nxt and st.blocked and st.generate
        st = pipeline.plan_step(_w(visa_type=visa, status=status, in_no="123", filed_date="2026-11-20"),
                                attachments=set(), doc_plan=None, position=None, today=TODAY)
        assert not st.blocked
    st = pipeline.plan_step(_w(status="Подаден Миграция"), attachments=set(), doc_plan=None, position=None,
                            today=TODAY)
    assert st.next == "Подаден АЗ" and not st.checks and not st.generate


def test_invitation_letter_only_for_india_and_nepal():
    w = _w(status="Получено разрешение", visa_interview_date="2026-12-01")
    texts = lambda iso: [c.text for c in pipeline.plan_step(w, attachments=set(), doc_plan=None, position=None,
                                                             iso3=iso, today=TODAY).checks]
    assert any("Invitation" in t for t in texts("IND")) and not any("Invitation" in t for t in texts("UZB"))


def test_stalled_after_three_days_and_deadlines():
    w = _w(status="Подаден АЗ", status_changed_at="2026-11-22 09:00:00", passport_expiry="2027-03-01",
           arrival_date="2026-11-27", residence_until=None)
    assert pipeline.stalled_days(w, TODAY) == 4
    assert pipeline.stalled_days(_w(status_changed_at="2026-11-25 09:00:00", status="Подаден АЗ"), TODAY) is None
    assert pipeline.stalled_days(_w(status="Работещ", status_changed_at="2026-01-01 09:00:00"), TODAY) is None
    dl = pipeline.deadlines(w, TODAY)
    texts = " | ".join(t for _, t, _ in dl)
    assert "Без движение 4 дни" in texts and "Пристигане: 27.11.2026 (утре)" in texts and "Паспортът изтича" in texts


# ------------------------------------------------------------------ end to end through the web app
def _db(app):
    return connect(Path(app.config["DATABASE"]))


def _step(client, cid):
    html = client.get(f"/candidates/{cid}").data.decode()
    return html[html.index('id="pipeline"'):html.index('id="schedule"')]


def _next(client, cid, expected):
    r = client.post(f"/candidates/{cid}/next-step", data={"expected": expected}, follow_redirects=True)
    return r.data.decode()


def _status(app, cid):
    c = _db(app)
    try:
        return c.execute("SELECT status FROM candidate WHERE id=?", (cid,)).fetchone()[0]
    finally:
        c.close()


def test_worker_walks_from_new_to_working(client, app):
    eid = _id_from(client.post("/employers/new", data=_employer("ПЪТ ООД")))
    c = _db(app)
    uzb = c.execute("SELECT id FROM country WHERE iso3='UZB'").fetchone()[0]
    c.close()
    r = client.post("/candidates/new", data={
        "name_lat": "Path Worker", "name_cyr": "Път Работник", "birth_date": "01.01.1990", "passport_no": "PW1",
        "citizenship_id": str(uzb), "birth_place": "City", "passport_issue_date": "01.01.2020",
        "passport_expiry": "01.01.2035", "employer_id": str(eid), "visa_type": "3 години",
        "position_new": "Общ работник"})
    cid = _id_from(r)
    panel = _step(client, cid)
    assert "Следваща стъпка: Изпратен легализация" in panel and 'class="cur"' in panel

    assert "„Нов“ → „Изпратен легализация“" in _next(client, cid, "Изпратен легализация")

    # documents step is blocked until the position has its justification and job description
    panel = _step(client, cid)
    assert "Обосновката на длъжността е празна" in panel and "disabled" in panel
    html = _next(client, cid, "Готови документи")
    assert "още не може" in html and _status(app, cid) == "Изпратен легализация"
    c = _db(app)
    pid = c.execute("SELECT position_id FROM candidate WHERE id=?", (cid,)).fetchone()[0]
    c.close()
    client.post(f"/positions/{pid}", data={"title": "Общ работник", "obosnovka": "Абзац едно.\nАбзац две.",
                                           "dh_duties": "Задължение"})
    html = _next(client, cid, "Готови документи")
    assert "Документите са генерирани" in html and _status(app, cid) == "Готови документи"
    c = _db(app)
    assert c.execute('SELECT count(*) FROM generation g JOIN "case" k ON k.id=g.case_id WHERE k.candidate_id=?',
                     (cid,)).fetchone()[0] == 1
    c.close()

    # filing needs the incoming number and date; then the set is generated again (control sheet)
    assert "още не може" in _next(client, cid, "Подаден Миграция")
    client.post(f"/schedule/{cid}", json={"in_no": "АА-123", "filed_date": "20.11.2026"})
    assert "„Готови документи“ → „Подаден Миграция“" in _next(client, cid, "Подаден Миграция")
    c = _db(app)
    assert c.execute('SELECT count(*) FROM generation g JOIN "case" k ON k.id=g.case_id WHERE k.candidate_id=?',
                     (cid,)).fetchone()[0] == 2
    c.close()

    dates = {"Получено разрешение": {"permit_date": "21.11.2026"},
             "Интервю за виза": {"visa_interview_date": "22.11.2026"},
             "Получена виза": {"visa_date": "23.11.2026"},
             "Пристигане България": {"arrival_date": "24.11.2026"}}
    for nxt in sched.STATUSES[4:]:
        if nxt in dates:
            assert "още не може" in _next(client, cid, nxt)
            client.post(f"/schedule/{cid}", json=dates[nxt])
        html = _next(client, cid, nxt)
        assert _status(app, cid) == nxt, (nxt, html[html.find("flash"):][:300])
    assert "последния етап" in _step(client, cid)
    c = _db(app)
    hist = [r[0] for r in c.execute("SELECT new_status FROM status_history WHERE candidate_id=? ORDER BY id", (cid,))]
    c.close()
    assert hist == list(sched.STATUSES[1:])


def test_stale_button_does_not_skip_a_step(client, app):
    eid = _id_from(client.post("/employers/new", data=_employer("ДВА ООД")))
    c = _db(app)
    uzb = c.execute("SELECT id FROM country WHERE iso3='UZB'").fetchone()[0]
    c.close()
    cid = _id_from(client.post("/candidates/new", data={
        "name_lat": "Stale Worker", "name_cyr": "Стар Бутон", "birth_date": "01.01.1990", "passport_no": "PW2",
        "citizenship_id": str(uzb), "birth_place": "City", "passport_issue_date": "01.01.2020",
        "passport_expiry": "01.01.2035", "employer_id": str(eid), "visa_type": "3 години",
        "position_new": "Общ работник"}))
    _next(client, cid, "Изпратен легализация")
    assert "сменен междувременно" in _next(client, cid, "Изпратен легализация")  # second click on an old page
    assert _status(app, cid) == "Изпратен легализация"


def test_dashboard_lists_workers_without_movement(client, app):
    eid = _id_from(client.post("/employers/new", data=_employer("ТРИ ООД")))
    c = _db(app)
    uzb = c.execute("SELECT id FROM country WHERE iso3='UZB'").fetchone()[0]
    c.close()
    cid = _id_from(client.post("/candidates/new", data={
        "name_lat": "Still Worker", "name_cyr": "Стои Работник", "birth_date": "01.01.1990", "passport_no": "PW3",
        "citizenship_id": str(uzb), "birth_place": "City", "passport_issue_date": "01.01.2020",
        "passport_expiry": "01.01.2035", "employer_id": str(eid), "visa_type": "3 години",
        "position_new": "Общ работник"}))
    c = _db(app)
    old = (date.today() - timedelta(days=5)).isoformat() + " 09:00:00"
    c.execute("UPDATE candidate SET created_at=? WHERE id=?", (old, cid))
    c.commit()
    c.close()
    html = client.get("/").data.decode()
    assert "без движение" in html and "Стои Работник" in html
    assert "Без движение 5 дни" in _step(client, cid)
