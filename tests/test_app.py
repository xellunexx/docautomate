import io
import re
from pathlib import Path

import docx

from conftest import needs_pdf
from docautomate.db import connect


def _id_from(resp):
    return int(re.search(r"/(\d+)(?:/edit)?$", resp.headers["Location"]).group(1))


def _setup_case(client, app):
    r = client.post("/employers/new", data={
        "name": "ТЕСТ ЕООД", "eik": "200 000 001", "address": "гр. София, ул. Тестова 1",
        "rep_name": "Мария Иванова Петрова", "rep_role": "управител", "rep_gender": "F", "rep_egn": "0000000000",
        "phone": "+359000", "email": "test@example.bg"})
    assert r.status_code == 302
    eid = _id_from(r)
    r = client.post(f"/employers/{eid}/positions/new", data={
        "title": "Общ работник", "nkpd": "96220001", "occupation_class": "неквалифицирани работници",
        "workplace": "гр. София, склад 3", "reporting_line": "Управителя",
        "obosnovka": "Първи абзац на обосновката.\nВтори абзац.", "dh_purpose": "Цел на длъжността.",
        "dh_duties": "Пренася товари\nПочиства", "dh_responsibilities": "Отговаря за реда",
        "dh_rights": "Да получава заплата", "dh_requirements": "физическа издръжливост",
        "dh_conditions": "Работа на открито."})
    assert r.status_code == 302
    pid = _id_from(r)
    conn = connect(Path(app.config["DATABASE"]))
    uzb = conn.execute("SELECT id FROM country WHERE iso3='UZB'").fetchone()[0]
    ctype = conn.execute("SELECT id FROM case_type WHERE legal_ground='24и' AND is_extension=0").fetchone()[0]
    conn.close()
    r = client.post("/candidates/new", data={
        "name_cyr": "Тестова Анна", "name_lat": "Testova Anna", "gender": "F", "birth_date": "05.06.1990",
        "birth_place": "Tashkent", "citizenship_id": str(uzb), "birth_country_id": str(uzb),
        "passport_no": "XX1234567", "passport_issue_date": "01.02.2020", "passport_expiry": "31.01.2030"})
    assert r.status_code == 302
    cid = _id_from(r)
    r = client.post("/cases/new", data={
        "candidate_id": cid, "employer_id": eid, "position_id": pid, "case_type_id": ctype,
        "contract_months": "36", "probation_months": "6", "salary": "1100", "currency": "евро", "pay_day": "30",
        "leave_days": "20", "extra_leave_days": "0", "notice_months": "3", "doc_city": "София",
        "doc_date": "01.12.2026", "notification_email": "notify@example.bg"})
    assert r.status_code == 302, r.data.decode()[:500]
    return eid, pid, cid, _id_from(r)


def test_pages_render(client, app):
    _setup_case(client, app)
    for url in ("/", "/candidates", "/employers", "/cases", "/templates", "/placeholders", "/case-types",
                "/countries", "/import", "/candidates/new", "/employers/new", "/cases/new", "/cases/1",
                "/cases/1/edit", "/candidates/1", "/employers/1", "/positions/1", "/cases/new?copy=1"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert "Docautomate" in r.data.decode()


def test_invalid_input_shows_errors_and_keeps_values(client):
    r = client.post("/candidates/new", data={"name_cyr": "", "birth_date": "32.13.1990", "name_lat": "Keep Me"})
    html = r.data.decode()
    assert r.status_code == 200
    assert "задължително поле" in html and "Невалидна дата" in html and "Keep Me" in html


def test_case_position_must_belong_to_employer(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    r = client.post("/employers/new", data={"name": "ДРУГА ООД"})
    other = _id_from(r)
    conn = connect(Path(app.config["DATABASE"]))
    ctype = conn.execute("SELECT id FROM case_type LIMIT 1").fetchone()[0]
    conn.close()
    r = client.post("/cases/new", data={"candidate_id": cid, "employer_id": other, "position_id": pid,
                                        "case_type_id": ctype})
    assert r.status_code == 200 and "не е на избрания работодател" in r.data.decode()


def test_duplicate_employer_is_friendly(client):
    client.post("/employers/new", data={"name": "ЕДНО ООД"})
    r = client.post("/employers/new", data={"name": "ЕДНО ООД"}, follow_redirects=True)
    assert "Вече има работодател с това име" in r.data.decode()


def test_case_page_lists_missing_fields(client, app):
    *_, case_id = _setup_case(client, app)
    html = client.get(f"/cases/{case_id}").data.decode()
    assert "ЛНЧ" in html  # used by Заявление and still empty
    assert "Заявление (Приложение № 3а)" in html and "Длъжностна характеристика" in html


@needs_pdf
def test_generate_pdfs_and_keep_history(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    r = client.post(f"/cases/{case_id}/generate", follow_redirects=True)
    html = r.data.decode()
    assert "Документите са генерирани." in html, html[:2000]
    conn = connect(Path(app.config["DATABASE"]))
    files = conn.execute("SELECT * FROM generated_file").fetchall()
    assert len(files) == 6 and all(f["pdf_name"] and not f["error"] for f in files)
    gen = conn.execute("SELECT * FROM generation").fetchone()
    folder = Path(app.config["DATA_DIR"]) / "generated" / gen["folder"]
    for f in files:
        assert (folder / f["pdf_name"]).read_bytes()[:4] == b"%PDF"
    td = next(f for f in files if "Трудов" in f["template_name"])
    text = "\n".join(c.text for t in docx.Document(str(folder / td["docx_name"])).tables
                     for row in t.rows for cell in row.cells for c in cell.paragraphs)
    assert "гражданка на Република Узбекистан, родена на 05.06.1990" in text
    assert "гражданка Республики Узбекистан, родилась 05.06.1990" in text
    assert "Мария Иванова Петрова в качеството ѝ на управител" in text
    assert "ТЕСТ ЕООД" in text and "200000001" in text  # spaces stripped from ЕИК

    # download routes
    assert client.get(f"/generated/{gen['id']}/{td['pdf_name']}").data[:4] == b"%PDF"
    z = client.get(f"/generated/{gen['id']}.zip")
    assert z.status_code == 200 and z.data[:2] == b"PK"
    assert client.get(f"/generated/{gen['id']}/../../docautomate.db").status_code == 404

    # edit + regenerate: the first set stays untouched
    first_pdf = (folder / td["pdf_name"]).read_bytes()
    client.post(f"/cases/{case_id}/edit", data={"candidate_id": cid, "employer_id": eid, "position_id": pid,
                                                 "case_type_id": conn.execute('SELECT case_type_id FROM "case"').fetchone()[0],
                                                 "salary": "1500", "contract_months": "36"})
    client.post(f"/cases/{case_id}/generate")
    gens = conn.execute("SELECT * FROM generation ORDER BY id").fetchall()
    assert len(gens) == 2 and gens[0]["folder"] != gens[1]["folder"]
    assert (folder / td["pdf_name"]).read_bytes() == first_pdf
    assert '"case.salary": "1500.00"' in gens[1]["snapshot"]
    # a case with generated documents cannot be deleted
    r = client.post(f"/cases/{case_id}/delete", follow_redirects=True)
    assert "не се изтрива" in r.data.decode()
    conn.close()


def test_copy_case_creates_new_case(client, app):
    eid, pid, cid, case_id = _setup_case(client, app)
    html = client.get(f"/cases/new?copy={case_id}").data.decode()
    assert 'value="1100"' in html
    conn = connect(Path(app.config["DATABASE"]))
    ctype = conn.execute('SELECT case_type_id FROM "case"').fetchone()[0]
    r = client.post(f"/cases/new?copy={case_id}", data={"candidate_id": cid, "employer_id": eid,
                                                        "position_id": pid, "case_type_id": ctype, "salary": "1100"})
    new_id = _id_from(r)
    assert new_id != case_id
    assert conn.execute('SELECT copied_from_id FROM "case" WHERE id=?', (new_id,)).fetchone()[0] == case_id
    conn.close()


def test_template_upload_validates(client, tmp_path):
    bad = docx.Document()
    bad.add_paragraph("{{ candidate.wrong_name }}")
    buf = io.BytesIO()
    bad.save(buf)
    r = client.post("/templates/upload", data={"file": (io.BytesIO(buf.getvalue()), "bad.docx"), "name": "Лоша"},
                    content_type="multipart/form-data")
    assert r.status_code == 422 and "candidate.wrong_name" in r.data.decode()

    good = docx.Document()
    good.add_paragraph("Нова бланка за {{ candidate.name_cyr }}")
    buf = io.BytesIO()
    good.save(buf)
    r = client.post("/templates/upload", data={"file": (io.BytesIO(buf.getvalue()), "good.docx"), "name": "Добра",
                                               "case_types": ["1"]},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Бланката е качена" in r.data.decode() and "Добра" in r.data.decode()

    r = client.post("/templates/upload", data={"file": (io.BytesIO(b"x"), "old.doc")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "трябва да е .docx" in r.data.decode()


def test_mrz_endpoint_with_pasted_text(client):
    text = ("P<UZBIVANOV<<PETR<<<<<<<<<<<<<<<<<<<<<<<<<<<\n")
    from test_mrz import make_mrz
    r = client.post("/mrz", data={"mrz_text": make_mrz(surname="IVANOV", given="PETR")})
    j = r.get_json()
    assert r.status_code == 200 and j["valid"]
    assert j["fields"]["name_lat"] == "Ivanov Petr"
    assert j["fields"]["birth_date"] == "01.01.1985"
    assert j["fields"]["passport_issued_by"] == "Република Узбекистан"
    assert j["fields"]["citizenship_id"]
    assert text  # keep linter quiet


def test_csv_import_page(client, tmp_path):
    from test_importer import _csv
    p = _csv(tmp_path)
    r = client.post("/import", data={"file": (open(p, "rb"), "c.csv")}, content_type="multipart/form-data")
    html = r.data.decode()
    assert "3 нови" in html and "Марс" in html


def test_masters_installed_once(app, tmp_path):
    from docautomate.app import create_app
    create_app(data_dir=Path(app.config["DATA_DIR"]), testing=True)  # second start
    conn = connect(Path(app.config["DATABASE"]))
    assert conn.execute("SELECT count(*) FROM doc_template").fetchone()[0] == 6
    n = conn.execute("SELECT count(*) FROM case_type_template").fetchone()[0]
    assert n == 6 + 2 + 2
    conn.close()


def test_every_button_and_nav_link_has_a_description(client, app):
    """Each button, button-styled link and menu item carries a title (tooltip) saying what it does."""
    _setup_case(client, app)
    client.post("/cases/1/generate")
    pages = ("/", "/candidates", "/employers", "/cases", "/templates", "/placeholders", "/case-types", "/countries",
             "/import", "/candidates/new", "/candidates/1", "/employers/1", "/positions/1", "/employers/1/positions/new",
             "/cases/new", "/cases/1", "/cases/1/edit", "/cases/new?copy=1")
    tag = re.compile(r"<(button|a)\b([^>]*)>", re.S)
    for url in pages:
        html = client.get(url).data.decode()
        header = html[html.index('<header'):html.index('</header>')]
        for kind, attrs in tag.findall(header):
            assert "title=" in attrs, f"{url}: menu <{kind}{attrs[:120]}> has no title"
        for kind, attrs in tag.findall(html[html.index('</header>'):]):
            if kind == "button" or 'class="btn' in attrs:
                assert "title=" in attrs, f"{url}: <{kind}{attrs[:120]}> has no title"


def test_replaced_master_is_not_reinstalled(client, app):
    from docautomate.app import create_app
    good = docx.Document()
    good.add_paragraph("Заменена обосновка за {{ candidate.name_cyr }}")
    buf = io.BytesIO()
    good.save(buf)
    conn = connect(Path(app.config["DATABASE"]))
    tid = conn.execute("SELECT id FROM doc_template WHERE master_key='obosnovka.docx'").fetchone()[0]
    client.post("/templates/upload", data={"file": (io.BytesIO(buf.getvalue()), "o.docx"), "replace_id": str(tid)},
                content_type="multipart/form-data")
    create_app(data_dir=Path(app.config["DATA_DIR"]), testing=True)  # restart
    assert conn.execute("SELECT count(*) FROM doc_template").fetchone()[0] == 6
    conn.close()


def test_same_template_names_do_not_overwrite_and_partial_pdf_kept(client, app, monkeypatch):
    from docautomate import render
    eid, pid, cid, case_id = _setup_case(client, app)
    conn = connect(Path(app.config["DATABASE"]))
    conn.execute("UPDATE doc_template SET name='Едно и също'")
    conn.commit()

    def fake_pdf(files, outdir):  # only the first file converts
        p = outdir / (files[0].stem + ".pdf")
        p.write_bytes(b"%PDF-1.4 fake")
        return {files[0]: p}
    monkeypatch.setattr(render, "to_pdf", fake_pdf)
    client.post(f"/cases/{case_id}/generate")
    rows = conn.execute("SELECT docx_name, pdf_name FROM generated_file").fetchall()
    assert len({r["docx_name"] for r in rows}) == 6  # six distinct files
    assert sum(1 for r in rows if r["pdf_name"]) == 1  # the converted one is kept
    conn.close()
