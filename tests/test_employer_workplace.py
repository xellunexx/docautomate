"""Workplace address of the employer (different from the registered seat) and the company documents panel."""
from docautomate.context import assemble

EMP = {"name": "ТЕСТ ЕООД", "eik": "200000000", "address": "гр. София, ул. Седалище 1", "rep_name": "Тест Тестов"}


def _ctx(cand=None, emp=None, pos=None):
    return assemble({"gender": "M", **(cand or {})}, {**EMP, **(emp or {})}, pos or {}, {}, {})


def test_workplace_falls_back_from_worker_to_position_to_employer_to_seat():
    assert _ctx(cand={"workplace_address": "Обект на работника"}, pos={"workplace": "Обект на длъжността"},
                emp={"workplace": "Обект на фирмата"})["position"]["workplace"] == "Обект на работника"
    assert _ctx(pos={"workplace": "Обект на длъжността"}, emp={"workplace": "Обект на фирмата"})["position"]["workplace"] \
        == "Обект на длъжността"
    assert _ctx(emp={"workplace": "Обект на фирмата"})["position"]["workplace"] == "Обект на фирмата"
    assert _ctx()["position"]["workplace"] == "гр. София, ул. Седалище 1", "no workplace anywhere: the seat"


def test_employer_workplace_placeholder():
    assert _ctx(emp={"workplace": "гр. Пловдив, цех 2"})["employer"]["workplace"] == "гр. Пловдив, цех 2"
    assert _ctx()["employer"]["workplace"] == "гр. София, ул. Седалище 1"
    assert _ctx()["employer"]["address"] == "гр. София, ул. Седалище 1", "the seat itself does not change"


def test_the_employer_page_shows_the_workplace_next_to_the_seat_and_the_company_documents(client, app):
    from test_app import _employer, _id_from
    r = client.post("/employers/new", data={**_employer("АДРЕС ЕООД"), "addresses": ["гр. Пловдив, цех 2", ""]})
    eid = _id_from(r)
    page = client.get(f"/employers/{eid}").get_data(as_text=True)
    seat, workplace = page.index("Седалище"), page.index("Адрес на месторабота (ако е различен от седалището)")
    assert seat < workplace < page.index("МОЛ – три имена"), "the workplace sits right under the seat"
    assert 'value="гр. Пловдив, цех 2"' in page
    assert "<h2>Фирмени документи</h2>" in page and f"/attachments/employer/{eid}/company" in page


def test_a_case_document_gets_the_employer_workplace(client, app):
    """Integration: the employer's first workplace address reaches the document context through the database."""
    from pathlib import Path
    from test_app import _setup_case
    from docautomate.context import build_context
    from docautomate.db import connect
    _eid, _pid, _cid, case_id = _setup_case(client, app)
    conn = connect(Path(app.config["DATABASE"]))
    eid = conn.execute('SELECT employer_id FROM "case" WHERE id=?', (case_id,)).fetchone()[0]
    conn.execute("UPDATE position SET workplace=''")
    conn.execute("UPDATE candidate SET workplace_address=''")
    conn.commit()
    assert build_context(conn, case_id)["position"]["workplace"] == "гр. София, ул. Тестова 1", "the seat"
    conn.execute("INSERT INTO employer_address (employer_id, address, sort_order) VALUES (?, 'гр. Варна, обект 3', 0)",
                 (eid,))
    conn.commit()
    ctx = build_context(conn, case_id)
    assert ctx["position"]["workplace"] == ctx["employer"]["workplace"] == "гр. Варна, обект 3"
    assert ctx["employer"]["address"] == "гр. София, ул. Тестова 1"
    conn.close()
