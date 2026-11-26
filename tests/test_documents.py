"""Stage 3 of the задание: document sets by visa type and country, generation from the worker profile."""
from pathlib import Path

import docx
import pytest

from docautomate import render
from docautomate.context import sample_context
from docautomate.db import connect

from test_app import _employer, _id_from

MASTERS = Path(__file__).resolve().parent.parent / "masters"


@pytest.fixture(autouse=True)
def no_pdf(monkeypatch):
    """Word/LibreOffice conversion is slow and not what these tests check."""
    monkeypatch.setattr(render, "to_pdf", lambda files, outdir: {})


def _db(app):
    return connect(Path(app.config["DATABASE"]))


def _iso(app, iso3):
    c = _db(app)
    try:
        return c.execute("SELECT id FROM country WHERE iso3=?", (iso3,)).fetchone()[0]
    finally:
        c.close()


def _worker(client, app, eid, iso3, visa, **extra):
    data = {"name_lat": f"Worker {iso3} {visa}", "name_cyr": f"Работник {iso3}", "birth_date": "01.01.1990",
            "passport_no": f"P-{iso3}-{visa}-{len(extra)}", "citizenship_id": str(_iso(app, iso3)),
            "birth_place": "City", "passport_issue_date": "01.01.2020", "passport_expiry": "01.01.2030",
            "employer_id": str(eid), "visa_type": visa, "position_new": "Общ работник", **extra}
    r = client.post("/candidates/new", data=data)
    assert r.status_code == 302, r.data.decode()[:400]
    return _id_from(r)


def _set_names(client, app, cid):
    html = client.get(f"/candidates/{cid}").data.decode()
    sec = html[html.index('id="documents"'):html.index('id="attachments"')]
    return sec[sec.index('class="tpl-list"'):sec.index('</ul>', sec.index('class="tpl-list"'))]  # the set only


@pytest.mark.parametrize("iso3,visa,present,absent", [
    ("UZB", "3 години", ["Трудов договор (BG/RU)", "Декларация за жилище", "Заявление", "Контролен лист", "Обосновка"],
     ["BG/EN", "Invitation Letter", "по чл. 28"]),
    ("KGZ", "Удължаване", ["Трудов договор (BG/RU)", "Декларация за жилище", "Заявление", "Обосновка"],
     ["BG/EN", "Invitation Letter", "90 дни"]),
    ("IND", "3 години", ["Трудов договор (BG/EN)", "Invitation Letter"], ["BG/RU", "по чл. 28"]),
    ("NPL", "3 години", ["Трудов договор (BG/EN)", "Invitation Letter"], ["BG/RU"]),
    ("PHL", "3 години", ["Трудов договор (BG/EN)"], ["BG/RU", "Invitation Letter"]),
    ("IND", "Удължаване", ["Трудов договор (BG/EN)"], ["Invitation Letter", "BG/RU"]),
    ("IND", "3 месеца", ["Трудов договор 90 дни (BG/EN)", "по чл. 28", "Условия на труд".replace("Условия на труд", "условия на труд"),
                         "Длъжностна характеристика"],
     ["Заявление", "Контролен лист", "Обосновка", "Invitation Letter", "(BG/RU)"]),
    ("UZB", "3 месеца", ["Трудов договор 90 дни (BG/RU)", "по чл. 28"], ["BG/EN", "Заявление"]),
])
def test_set_follows_visa_type_and_country(client, app, iso3, visa, present, absent):
    eid = _id_from(client.post("/employers/new", data=_employer("ФИРМА ООД")))
    cid = _worker(client, app, eid, iso3, visa)
    sec = _set_names(client, app, cid)
    for name in present:
        assert name in sec, (iso3, visa, name)
    for name in absent:
        assert name not in sec, (iso3, visa, name)


def test_generate_needs_visa_type_and_then_fills_the_set(client, app):
    eid = _id_from(client.post("/employers/new", data=_employer("ФИРМА ООД")))
    cid = _worker(client, app, eid, "IND", "")
    r = client.post(f"/candidates/{cid}/generate", follow_redirects=True)
    assert "Изберете „Тип виза“" in r.data.decode()
    c = _db(app)
    assert c.execute('SELECT count(*) FROM "case"').fetchone()[0] == 0
    c.execute("UPDATE candidate SET visa_type='3 години', residence_address='гр. София, ул. Жилищна 1' WHERE id=?",
              (cid,))
    c.commit()
    r = client.post(f"/candidates/{cid}/generate", follow_redirects=True)
    html = r.data.decode()
    assert "Документите са генерирани" in html
    case = c.execute('SELECT * FROM "case" WHERE candidate_id=?', (cid,)).fetchone()
    assert case["employer_id"] == eid and case["contract_months"] == 36
    files = [f["template_name"] for f in c.execute("SELECT * FROM generated_file")]
    assert "Invitation Letter" in files and "Трудов договор (BG/EN) – чернова" in files
    assert not any("BG/RU" in f for f in files)
    assert "Всички Word (zip)" in html
    # a second run reuses the case (no duplicate) and adds a new set
    client.post(f"/candidates/{cid}/generate")
    assert c.execute('SELECT count(*) FROM "case"').fetchone()[0] == 1
    assert c.execute("SELECT count(*) FROM generation").fetchone()[0] == 2
    gen = c.execute("SELECT id FROM generation ORDER BY id DESC LIMIT 1").fetchone()[0]
    z = client.get(f"/generated/{gen}.zip?kind=docx")
    assert z.status_code == 200 and z.data[:2] == b"PK"


def test_generated_documents_carry_the_worker_data(client, app):
    eid = _id_from(client.post("/employers/new", data={**_employer("ДАННИ ООД"), "addresses": ["гр. Варна, обект 7"]}))
    cid = _worker(client, app, eid, "NPL", "3 години", workplace_address="гр. Варна, обект 7",
                  residence_address="гр. Варна, ж.к. Тест, бл. 2", gender="F")
    client.post(f"/candidates/{cid}/generate")
    c = _db(app)
    gen = c.execute("SELECT * FROM generation").fetchone()
    folder = Path(app.config["DATA_DIR"]) / "generated" / gen["folder"]
    texts = {}
    for f in c.execute("SELECT * FROM generated_file WHERE generation_id=?", (gen["id"],)):
        d = docx.Document(folder / f["docx_name"])
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                for cell in row.cells:
                    parts += [p.text for p in cell.paragraphs]
        texts[f["template_name"]] = "\n".join(parts)
    inv = texts["Invitation Letter"]
    assert "Federal Democratic Republic of Nepal" in inv and "New Delhi, India" in inv
    assert "Ms Worker NPL" in inv and "enabling her" in inv and "гр. Варна, обект 7" in inv
    en = texts["Трудов договор (BG/EN) – чернова"]
    assert "citizen of the Federal Democratic Republic of Nepal" in en and "36 months" in en
    assert "гражданка на Федерална демократична република Непал" in en  # the Bulgarian half
    assert "гр. Варна, ж.к. Тест, бл. 2" in texts["Декларация за жилище"]


def test_seasonal_housing_lists_workers_at_the_same_address(client, app):
    eid = _id_from(client.post("/employers/new", data=_employer("СЕЗОН ООД")))
    a = _worker(client, app, eid, "IND", "3 месеца", residence_address="с. Поле 1", name_cyr="Първи Сезонен")
    _worker(client, app, eid, "IND", "3 месеца", residence_address="с. Поле 1", name_cyr="Втори Сезонен",
            passport_no="S2")
    _worker(client, app, eid, "IND", "3 месеца", residence_address="друг адрес", name_cyr="Трети Другаде",
            passport_no="S3")
    client.post(f"/candidates/{a}/generate")
    c = _db(app)
    f = c.execute("SELECT g.folder, f.docx_name FROM generated_file f JOIN generation g ON g.id=f.generation_id"
                  " WHERE f.template_name LIKE '%чл. 28%'").fetchone()
    text = "\n".join(p.text for p in docx.Document(Path(app.config["DATA_DIR"]) / "generated" / f[0] / f[1]).paragraphs)
    assert "- Първи Сезонен" in text and "- Втори Сезонен" in text and "Трети Другаде" not in text


def test_extension_uses_the_extension_justification(client, app):
    from docautomate.context import assemble
    pos = {"obosnovka": "Първоначален текст.", "obosnovka_ext": "Текст за удължаване."}
    ctx = assemble({}, {}, pos, {}, {"is_extension": 1})
    assert ctx["position"]["obosnovka_paragraphs"] == ["Текст за удължаване."]
    ctx = assemble({}, {}, pos, {}, {"is_extension": 0})
    assert ctx["position"]["obosnovka_paragraphs"] == ["Първоначален текст."]
    ctx = assemble({}, {}, {"obosnovka": "Само първоначален."}, {}, {"is_extension": 1})
    assert ctx["position"]["obosnovka_paragraphs"] == ["Само първоначален."]


def test_country_rule_on_templates_page_is_editable(client, app):
    c = _db(app)
    tid = c.execute("SELECT id FROM doc_template WHERE master_key='trudov-dogovor-bg-ru.docx'").fetchone()[0]
    types = [r[0] for r in c.execute("SELECT case_type_id FROM case_type_template WHERE template_id=?", (tid,))]
    client.post(f"/templates/{tid}/settings", data={"name": "Трудов договор (BG/RU)", "is_active": "1",
                                                    "sort_order": "30", "countries": "kgz; uzb, tjk",
                                                    "case_types": [str(t) for t in types]})
    assert c.execute("SELECT countries FROM doc_template WHERE id=?", (tid,)).fetchone()[0] == "KGZ,TJK,UZB"


@pytest.mark.parametrize("name", ["trudov-dogovor-bg-en.docx", "trudov-dogovor-90-bg-ru.docx",
                                  "trudov-dogovor-90-bg-en.docx", "deklaracia-zhilishte.docx",
                                  "deklaracia-zhilishte-chl28.docx", "invitation-letter.docx"])
def test_new_masters_fill_without_leftover_tags(tmp_path, name):
    out = render.fill_docx(MASTERS / name, sample_context(), tmp_path / "out.docx")
    d = docx.Document(out)
    text = "\n".join(p.text for p in d.paragraphs)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                text += "\n".join(p.text for p in cell.paragraphs)
    assert "{{" not in text and "{%" not in text
    assert "ПРИМЕР ЕООД" in text


def test_bg_en_contract_names_english_in_both_halves(tmp_path):
    out = render.fill_docx(MASTERS / "trudov-dogovor-bg-en.docx", sample_context(), tmp_path / "en.docx")
    left, right = docx.Document(out).tables[0].rows[0].cells
    bg, en = "\n".join(p.text for p in left.paragraphs), "\n".join(p.text for p in right.paragraphs)
    assert "на български и английски език" in bg and "руски" not in bg
    assert "Bulgarian and English" in en and "Republic of Uzbekistan" in en
