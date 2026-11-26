"""Stage 1 of the задание: База Работодатели and База Работници."""
import io
import re
import sqlite3
from pathlib import Path

from docautomate.db import connect

from test_app import _employer, _id_from, _setup_case


def _db(app):
    return connect(Path(app.config["DATABASE"]))


def _worker(eid, country, **extra):
    return {"name_lat": "Testov Test", "name_cyr": "Тестов Тест", "birth_date": "01.01.1990",
            "passport_no": "AA0000001", "citizenship_id": str(country), "birth_place": "Tashkent",
            "passport_issue_date": "01.01.2020", "passport_expiry": "01.01.2030", "employer_id": str(eid), **extra}


def _uzb(app):
    c = _db(app)
    try:
        return c.execute("SELECT id FROM country WHERE iso3='UZB'").fetchone()[0]
    finally:
        c.close()


def test_employer_needs_the_six_required_fields(client, app):
    r = client.post("/employers/new", data={"name": "НЕПЪЛНА ООД", "eik": "1"})
    html = r.data.decode()
    assert r.status_code == 200 and "Нищо не е записано" in html
    for label in ("Седалище", "МОЛ", "Телефон за контакт", "Имейл за контакт"):
        assert f"{label}" in html and "задължително поле" in html
    assert _db(app).execute("SELECT count(*) FROM employer").fetchone()[0] == 0
    r = client.post("/employers/new", data=_employer("ПЪЛНА ООД", email="not-an-email"))
    assert r.status_code == 200 and "невалиден имейл" in r.data.decode()
    r = client.post("/employers/new", data=_employer("ПЪЛНА ООД"))
    assert r.status_code == 302


def test_employer_addresses_and_unique_numbers(client, app):
    r = client.post("/employers/new", data={**_employer("АДРЕСИ ООД"),
                                            "addresses": ["гр. София, склад 1", "  ", "гр. Пловдив,  цех 2",
                                                          "гр. София, склад 1"]})
    eid = _id_from(r)
    c = _db(app)
    assert [r[0] for r in c.execute("SELECT address FROM employer_address WHERE employer_id=? ORDER BY sort_order",
                                    (eid,))] == ["гр. София, склад 1", "гр. Пловдив, цех 2"]
    first = c.execute("SELECT ref_no FROM employer WHERE id=?", (eid,)).fetchone()[0]
    assert first == 101
    r2 = client.post("/employers/new", data=_employer("ВТОРА ООД"))
    second = c.execute("SELECT ref_no FROM employer WHERE id=?", (_id_from(r2),)).fetchone()[0]
    assert second == 102
    # a number is never reused, even after the newest record is deleted
    c.execute("DELETE FROM employer WHERE ref_no=102")
    c.commit()
    r3 = client.post("/employers/new", data=_employer("ТРЕТА ООД"))
    assert c.execute("SELECT ref_no FROM employer WHERE id=?", (_id_from(r3),)).fetchone()[0] == 103
    # the address list can be edited; removing all leaves none
    client.post(f"/employers/{eid}", data={**_employer("АДРЕСИ ООД"), "addresses": ["гр. Варна"]})
    assert [r[0] for r in c.execute("SELECT address FROM employer_address WHERE employer_id=?", (eid,))] == ["гр. Варна"]
    assert "№ 101" in client.get(f"/employers/{eid}").data.decode()


def test_worker_requires_fields_and_an_existing_employer(client, app):
    uzb = _uzb(app)
    r = client.post("/candidates/new", data={"name_cyr": "Само Име"})
    html = r.data.decode()
    assert r.status_code == 200
    for label in ("Име на латиница", "Дата на раждане", "Номер на паспорт", "Страна на произход",
                  "Място на раждане", "Дата на издаване на паспорта", "Валидност на паспорта",
                  "изберете работодател"):
        assert label in html, label
    r = client.post("/candidates/new", data=_worker(9999, uzb))
    assert r.status_code == 200 and "изберете работодател от списъка" in r.data.decode()
    eid = _id_from(client.post("/employers/new", data=_employer("Р ООД")))
    r = client.post("/candidates/new", data=_worker(eid, uzb, visa_type="3 години", contact="агент Иван",
                                                    residence_address="гр. София, ж.к. Тест"))
    assert r.status_code == 302
    row = _db(app).execute("SELECT * FROM candidate WHERE id=?", (_id_from(r),)).fetchone()
    assert row["employer_id"] == eid and row["visa_type"] == "3 години" and row["ref_no"] == 1001
    assert row["residence_address"] == "гр. София, ж.к. Тест" and row["contact"] == "агент Иван"
    r = client.post("/candidates/new", data=_worker(eid, uzb, visa_type="5 години"))
    assert r.status_code == 200 and "невалиден избор" in r.data.decode()


def test_worker_position_and_workplace_come_from_the_employer(client, app):
    uzb = _uzb(app)
    eid = _id_from(client.post("/employers/new", data={**_employer("ЕДНО ООД"), "addresses": ["Обект 1"]}))
    other = _id_from(client.post("/employers/new", data={**_employer("ДРУГО ООД"), "addresses": ["Обект 2"]}))
    # a new position typed by hand is created under the chosen employer
    r = client.post("/candidates/new", data=_worker(eid, uzb, position_new="Готвач", workplace_address="Обект 1"))
    assert r.status_code == 302
    c = _db(app)
    w = c.execute("SELECT * FROM candidate WHERE id=?", (_id_from(r),)).fetchone()
    p = c.execute("SELECT * FROM position WHERE id=?", (w["position_id"],)).fetchone()
    assert p["employer_id"] == eid and p["title"] == "Готвач" and w["workplace_address"] == "Обект 1"
    # typing the same title again reuses it
    client.post("/candidates/new", data=_worker(eid, uzb, passport_no="AA2", position_new="готвач"))
    assert c.execute("SELECT count(*) FROM position WHERE employer_id=?", (eid,)).fetchone()[0] == 1
    # another employer's address or position is refused
    r = client.post("/candidates/new", data=_worker(eid, uzb, workplace_address="Обект 2"))
    assert r.status_code == 200 and "не е от адресите" in r.data.decode()
    r = client.post("/candidates/new", data=_worker(other, uzb, position_id=str(p["id"])))
    assert r.status_code == 200 and "не е на избрания работодател" in r.data.decode()
    # an invalid form creates no position
    client.post("/candidates/new", data=_worker(other, uzb, name_lat="", position_new="Призрак"))
    assert not c.execute("SELECT 1 FROM position WHERE title='Призрак'").fetchone()


def test_worker_table_filters_and_grouping(client, app):
    uzb = _uzb(app)
    c = _db(app)
    ind = c.execute("SELECT id FROM country WHERE iso3='IND'").fetchone()[0]
    a = _id_from(client.post("/employers/new", data=_employer("АЛФА ООД")))
    b = _id_from(client.post("/employers/new", data=_employer("БЕТА ООД")))
    client.post("/candidates/new", data=_worker(a, uzb, name_cyr="Първи Узбек", visa_type="3 години"))
    client.post("/candidates/new", data=_worker(b, ind, name_cyr="Втори Индиец", passport_no="B2", visa_type="3 месеца"))
    html = client.get(f"/candidates?employer={a}").data.decode()
    assert "Първи Узбек" in html and "Втори Индиец" not in html
    html = client.get(f"/candidates?country={ind}").data.decode()
    assert "Втори Индиец" in html and "Първи Узбек" not in html
    html = client.get("/candidates?visa=3+месеца").data.decode()
    assert "Втори Индиец" in html and "Първи Узбек" not in html
    html = client.get("/candidates?group=employer").data.decode()
    html = html[html.index('class="group-head"'):]  # skip the filter dropdown, which also lists employers
    assert html.index("АЛФА ООД") < html.index("Първи Узбек") < html.index("БЕТА ООД") < html.index("Втори Индиец")
    assert "1001" in client.get("/candidates?q=1001").data.decode()


def test_attachments_upload_open_delete(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    r = client.post(f"/attachments/worker/{cid}/passport",
                    data={"files": [(io.BytesIO(b"PDF1"), "pasport.pdf"), (io.BytesIO(b"JPG"), "sud.jpg")]},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    html = client.get(f"/candidates/{cid}").data.decode()
    assert "pasport.pdf" in html and "sud.jpg" in html and "Медицинска застраховка" in html
    aid = int(re.search(r'/attachments/(\d+)"', html).group(1))
    assert client.get(f"/attachments/{aid}").data == b"PDF1"
    assert client.post(f"/attachments/worker/{cid}/unknown", data={}).status_code == 404
    assert client.post("/attachments/worker/9999/passport", data={}).status_code == 404
    client.post(f"/attachments/employer/{eid}/company", data={"files": [(io.BytesIO(b"X"), "dogovor.docx")]},
                content_type="multipart/form-data")
    assert "dogovor.docx" in client.get(f"/employers/{eid}").data.decode()
    stored = _db(app).execute("SELECT stored_name FROM attachment WHERE id=?", (aid,)).fetchone()[0]
    path = Path(app.config["DATA_DIR"]) / "attachments" / stored
    assert path.exists()
    client.post(f"/attachments/{aid}/delete")
    assert not path.exists() and client.get(f"/attachments/{aid}").status_code == 404


def test_new_case_takes_employer_position_and_visa_from_worker(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    c = _db(app)
    c.execute("UPDATE candidate SET visa_type='Удължаване' WHERE id=?", (cid,))
    c.commit()
    ext = c.execute("SELECT id FROM case_type WHERE is_extension=1").fetchone()[0]
    html = client.get(f"/cases/new?candidate_id={cid}").data.decode()
    assert re.search(rf'<option value="{eid}"\s+selected', html)
    assert re.search(rf'<option value="{pid}"[^>]*selected', html)
    assert re.search(rf'<option value="{ext}"\s+selected', html)


def test_old_database_is_migrated(tmp_path):
    """A v1 database (no worker employer, no numbers) gets the new columns and keeps its data."""
    from docautomate import db as dbm
    from docautomate.app import create_app
    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "docautomate.db")
    conn.executescript(dbm.SCHEMA)
    conn.execute("INSERT INTO case_type (id, name, residence_period, is_extension) VALUES (1, 'Виза 3 месеца', '3 месеца', 0)")
    conn.execute("INSERT INTO employer (id, name) VALUES (5, 'СТАРА ООД')")
    conn.execute("INSERT INTO position (id, employer_id, title, workplace) VALUES (7, 5, 'Работник', 'с. Старо')")
    conn.execute("INSERT INTO candidate (id, name_cyr) VALUES (3, 'Стар Работник'), (4, 'Без Случай')")
    conn.execute('INSERT INTO "case" (candidate_id, employer_id, position_id, case_type_id) VALUES (3, 5, 7, 1)')
    conn.commit()
    conn.close()
    create_app(data_dir=data, testing=True)
    c = connect(data / "docautomate.db")
    w = c.execute("SELECT * FROM candidate WHERE id=3").fetchone()
    assert (w["employer_id"], w["position_id"], w["visa_type"], w["workplace_address"]) == (5, 7, "3 месеца", "с. Старо")
    assert [r[0] for r in c.execute("SELECT ref_no FROM candidate ORDER BY id")] == [1001, 1002]
    assert c.execute("SELECT ref_no FROM employer").fetchone()[0] == 101
    assert c.execute("SELECT address FROM employer_address WHERE employer_id=5").fetchone()[0] == "с. Старо"
    # running the migration again changes nothing
    create_app(data_dir=data, testing=True)
    assert c.execute("SELECT count(*) FROM employer_address").fetchone()[0] == 1
    assert [r[0] for r in c.execute("SELECT ref_no FROM candidate ORDER BY id")] == [1001, 1002]
