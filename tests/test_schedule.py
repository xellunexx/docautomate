"""Stage 2 of the задание: Справки (График), statuses, delay thresholds, Addition info."""
from datetime import date, timedelta
from pathlib import Path

from docautomate import schedule as sched
from docautomate.db import connect

from test_app import _employer, _id_from, _setup_case


def _db(app):
    return connect(Path(app.config["DATABASE"]))


def test_thresholds_follow_the_example_in_the_spec():
    # „Подаден Миграция“: day 40 nothing, 41 orange, 60 still orange, 61 red
    assert sched.delay("Подаден Миграция", 40) == ""
    assert sched.delay("Подаден Миграция", 41) == "orange"
    assert sched.delay("Подаден Миграция", 60) == "orange"
    assert sched.delay("Подаден Миграция", 61) == "red"
    assert sched.delay("Нов", 15) == "orange" and sched.delay("Нов", 22) == "red"
    assert sched.delay("Работещ", 999) == ""          # not in the table: no colour
    assert sched.delay("Отказ", 999) == ""
    assert sched.days_over("Подаден Миграция", 65, "red") == 5


def test_residence_bands_each_record_in_one_band():
    assert sched.residence_band(120) == "yellow" and sched.residence_band(91) == "yellow"
    assert sched.residence_band(90) == "orange" and sched.residence_band(61) == "orange"
    assert sched.residence_band(60) == "red" and sched.residence_band(0) == "red"
    assert sched.residence_band(-1) == "expired" and sched.residence_band(None) == "none"
    assert sched.residence_band(121) == ""


def test_new_counts_from_creation_others_from_the_manual_change():
    today = date(2026, 12, 31)
    row = {"status": "Нов", "status_changed_at": "2026-12-30 10:00:00", "created_at": "2026-12-01 09:00:00",
           "residence_until": "2027-02-14"}
    info = sched.addition_info(row, today)
    assert info["days_in_status"] == 30 and info["delay"] == "red" and info["residence_days"] == 45
    row["status"] = "Готови документи"
    assert sched.addition_info(row, today)["days_in_status"] == 1


def test_new_worker_starts_as_new(client, app):
    *_, cid, case_id = _setup_case(client, app)
    w = _db(app).execute("SELECT status, status_changed_at, created_at FROM candidate WHERE id=?", (cid,)).fetchone()
    assert w["status"] == "Нов" and w["status_changed_at"] == w["created_at"]


def test_dates_save_inline_and_never_change_status(client, app):
    *_, cid, case_id = _setup_case(client, app)
    r = client.post(f"/schedule/{cid}", json={"filed_date": "05.11.2026", "in_no": "ВХ-1"})
    assert r.status_code == 200 and r.json["ok"] and r.json["values"]["filed_date"] == "05.11.2026"
    c = _db(app)
    w = c.execute("SELECT * FROM candidate WHERE id=?", (cid,)).fetchone()
    assert (w["filed_date"], w["in_no"], w["status"]) == ("2026-11-05", "ВХ-1", "Нов")
    assert c.execute("SELECT count(*) FROM status_history").fetchone()[0] == 0
    r = client.post(f"/schedule/{cid}", json={"permit_date": "32.13.2026"})
    assert r.status_code == 422 and "Невалидна дата" in r.json["errors"]["permit_date"]
    # unknown fields are ignored, never written
    client.post(f"/schedule/{cid}", json={"name_cyr": "Хакер"})
    assert c.execute("SELECT name_cyr FROM candidate WHERE id=?", (cid,)).fetchone()[0] == "Тестова Анна"


def test_manual_status_change_writes_history(client, app):
    *_, cid, case_id = _setup_case(client, app)
    r = client.post(f"/schedule/{cid}", json={"status": "Подаден Миграция"})
    assert r.json["ok"] and r.json["status"] == "Подаден Миграция" and r.json["days_in_status"] == 0
    c = _db(app)
    h = c.execute("SELECT * FROM status_history WHERE candidate_id=?", (cid,)).fetchall()
    assert [(x["old_status"], x["new_status"]) for x in h] == [("Нов", "Подаден Миграция")]
    # same status again: no new history row
    client.post(f"/schedule/{cid}", json={"status": "Подаден Миграция"})
    assert c.execute("SELECT count(*) FROM status_history").fetchone()[0] == 1
    r = client.post(f"/schedule/{cid}", json={"status": "Измислен"})
    assert r.status_code == 422
    # the profile form does the same
    r = client.post(f"/schedule/{cid}", data={"status": "Получено разрешение", "arrival_date": "01.01.2027"})
    assert r.status_code == 302
    w = c.execute("SELECT status, arrival_date FROM candidate WHERE id=?", (cid,)).fetchone()
    assert tuple(w) == ("Получено разрешение", "2027-01-01")
    assert "История на статуса" in client.get(f"/candidates/{cid}").data.decode()


def test_schedule_page_colours_filters_groups_and_sorts(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    c = _db(app)
    old = (date.today() - timedelta(days=61)).isoformat() + " 08:00:00"
    c.execute("UPDATE candidate SET status='Подаден Миграция', status_changed_at=?, visa_type='3 години',"
              " filed_date='2026-01-10', residence_until=? WHERE id=?",
              (old, (date.today() + timedelta(days=50)).isoformat(), cid))
    c.commit()
    other = _id_from(client.post("/employers/new", data=_employer("ВТОРА ООД")))
    c.execute("INSERT INTO candidate (name_cyr, name_lat, employer_id, visa_type, filed_date) VALUES"
              " ('Втори Работник', 'Second Worker', ?, '3 месеца', '2026-03-01')", (other,))
    c.commit()
    html = client.get("/schedule").data.decode()
    assert "delay-red" in html and "Addition info" in html and "res-red" in html
    html = client.get(f"/schedule?employer={eid}").data.decode()
    assert "Testova Anna" in html and "Second Worker" not in html
    html = client.get(f"/schedule?employer={eid}&employer={other}").data.decode()
    assert "Testova Anna" in html and "Second Worker" in html
    html = client.get("/schedule?delay=red").data.decode()
    assert "Testova Anna" in html and "Second Worker" not in html
    html = client.get("/schedule?status=Нов").data.decode()
    assert "Second Worker" in html and "Testova Anna" not in html
    html = client.get("/schedule?sort=filed_date&dir=desc").data.decode()
    assert html.index("Second Worker") < html.index("Testova Anna")
    html = client.get("/schedule?sort=filed_date&dir=asc").data.decode()
    assert html.index("Testova Anna") < html.index("Second Worker")
    html = client.get("/schedule?group=status").data.decode()
    body = html[html.index('class="group-head"'):]
    assert body.index("Нов") < body.index("Подаден Миграция")
    assert client.get("/schedule?group=contact").status_code == 200


def test_old_free_text_status_is_kept_in_notes(tmp_path):
    import sqlite3

    from docautomate import db as dbm
    from docautomate.app import create_app
    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "docautomate.db")
    conn.executescript(dbm.SCHEMA)
    conn.execute("INSERT INTO candidate (name_cyr, status) VALUES ('А', 'Работещ'), ('Б', 'чака документи'), ('В', '')")
    conn.commit()
    conn.close()
    create_app(data_dir=data, testing=True)
    c = connect(data / "docautomate.db")
    rows = c.execute("SELECT name_cyr, status, notes, status_changed_at FROM candidate ORDER BY id").fetchall()
    assert [r["status"] for r in rows] == ["Работещ", "Нов", "Нов"]
    assert "Стар статус: чака документи" in rows[1]["notes"]
    assert all(r["status_changed_at"] for r in rows)
