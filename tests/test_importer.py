import csv

from docautomate import importer
from docautomate.db import connect, init_db

HEADER = ["Име", "Име лат", "Дата на раждане", "Номер паспорт", "Държава", "Фирма", "Позиция", "Тип виза",
          "Статус", "Контакт", "Вх.номер", "Дата на входиране"]
ROWS = [
    ["Тестов Тест", "Testov Test", "25/12/1990", "XX0000001", "Узбекистан", "ТЕСТ ЕООД", "Общ работник",
     "3 години", "Нов", "0888000001", "", ""],
    ["Примерна Мария", "Primerna Maria", "1/2/1995", "XX0000002", "Нигеря", "ТЕСТ ЕООД", "Готвач",
     "Удължаване", "Работещ", "", "123", "3/4/2026"],
    ["Без Държава", "", "", "", "Марс", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", "", "", ""],
]


def _csv(tmp_path, rows=ROWS):
    p = tmp_path / "c.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)
    return p


def _db(tmp_path):
    conn = connect(tmp_path / "t.db")
    init_db(conn)
    return conn


def test_csv_import_and_rerun_is_idempotent(tmp_path):
    conn = _db(tmp_path)
    recs = importer.read_csv(_csv(tmp_path))
    s1 = importer.import_records(conn, recs)
    assert s1.candidates_new == 3 and s1.employers_new == 1 and s1.positions_new == 2 and s1.cases_new == 2
    assert s1.countries_unmatched == {"Марс": 1}
    assert len(s1.skipped) == 1
    row = conn.execute("SELECT * FROM candidate WHERE passport_no='XX0000001'").fetchone()
    assert row["birth_date"] == "1990-12-25"
    nga = conn.execute("SELECT c.name FROM candidate ca JOIN country c ON c.id=ca.citizenship_id"
                       " WHERE passport_no='XX0000002'").fetchone()
    assert nga["name"] == "Нигерия"  # typo alias matched
    ext = conn.execute('SELECT ct.name, c.reg_no, c.reg_date FROM "case" c JOIN case_type ct ON ct.id=c.case_type_id'
                       " JOIN candidate ca ON ca.id=c.candidate_id WHERE ca.passport_no='XX0000002'").fetchone()
    assert ext["name"] == "Удължаване" and ext["reg_no"] == "123" and ext["reg_date"] == "2026-04-03"

    # staff edit in the app must survive a re-import
    conn.execute("UPDATE candidate SET name_lat='Edited' WHERE passport_no='XX0000001'")
    conn.commit()
    s2 = importer.import_records(conn, importer.read_csv(_csv(tmp_path)))
    assert s2.candidates_new == 0 and s2.cases_new == 0 and s2.employers_new == 0
    assert conn.execute("SELECT name_lat FROM candidate WHERE passport_no='XX0000001'").fetchone()[0] == "Edited"
    assert conn.execute("SELECT count(*) FROM candidate").fetchone()[0] == 3


def test_month_first_dates_detected(tmp_path):
    rows = [["A", "", "12/25/1990", "P1", "", "", "", "", "", "", "", ""],
            ["B", "", "1/2/1995", "P2", "", "", "", "", "", "", "", ""]]
    conn = _db(tmp_path)
    importer.import_records(conn, importer.read_csv(_csv(tmp_path, rows)))
    assert conn.execute("SELECT birth_date FROM candidate WHERE passport_no='P2'").fetchone()[0] == "1995-01-02"


class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, headers, params, timeout):
        self.calls.append(dict(params))
        if "offset" not in params:
            return FakeResp({"records": [{"id": "rec1", "fields": {"Име": "А", "Номер паспорт": "Z1",
                                                                  "Дата на раждане": "1990-01-02"}}],
                             "offset": "o1"})
        return FakeResp({"records": [{"id": "rec2", "fields": {"Име": "Б", "Фирма": "Ф ООД",
                                                              "Тип виза": "3 години"}}]})


def test_airtable_pagination_and_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(importer.time, "sleep", lambda s: None)
    sess = FakeSession()
    recs = importer.fetch_airtable("tok", session=sess)
    assert [r["_id"] for r in recs] == ["rec1", "rec2"] and len(sess.calls) == 2
    conn = _db(tmp_path)
    importer.import_records(conn, recs)
    importer.import_records(conn, recs)  # rerun: matched by Airtable id
    assert conn.execute("SELECT count(*) FROM candidate").fetchone()[0] == 2
    assert conn.execute('SELECT count(*) FROM "case"').fetchone()[0] == 1
    assert conn.execute("SELECT birth_date FROM candidate WHERE airtable_id='rec1'").fetchone()[0] == "1990-01-02"


def test_country_alias_case_insensitive(tmp_path):
    from docautomate.db import find_country
    conn = _db(tmp_path)
    conn.execute("UPDATE country SET aliases='Uzbekistan' WHERE iso3='UZB'")
    assert find_country(conn, "uzbekistan")["iso3"] == "UZB"


def test_latin_only_record_not_duplicated(tmp_path):
    rows = [["", "Example Person", "01.02.1990", "", "", "", "", "", "", "", "", ""]]
    conn = _db(tmp_path)
    importer.import_records(conn, importer.read_csv(_csv(tmp_path, rows)))
    importer.import_records(conn, importer.read_csv(_csv(tmp_path, rows)))
    assert conn.execute("SELECT count(*) FROM candidate").fetchone()[0] == 1


def test_api_import_links_case_from_earlier_csv(tmp_path):
    conn = _db(tmp_path)
    importer.import_records(conn, importer.read_csv(_csv(tmp_path)))
    n_cases = conn.execute('SELECT count(*) FROM "case"').fetchone()[0]
    api = [{"_id": "recX", "Име": "Тестов Тест", "Номер паспорт": "XX0000001", "Фирма": "ТЕСТ ЕООД",
            "Позиция": "Общ работник", "Тип виза": "3 години"}]
    importer.import_records(conn, api)
    assert conn.execute('SELECT count(*) FROM "case"').fetchone()[0] == n_cases
    assert conn.execute('SELECT count(*) FROM "case" WHERE airtable_id=\'recX\'').fetchone()[0] == 1


def test_api_record_for_other_position_is_not_merged(tmp_path):
    conn = _db(tmp_path)
    importer.import_records(conn, importer.read_csv(_csv(tmp_path)))
    n_cases = conn.execute('SELECT count(*) FROM "case"').fetchone()[0]
    api = [{"_id": "recY", "Име": "Тестов Тест", "Номер паспорт": "XX0000001", "Фирма": "ТЕСТ ЕООД",
            "Позиция": "Шофьор", "Тип виза": "3 години"}]
    importer.import_records(conn, api)
    assert conn.execute('SELECT count(*) FROM "case"').fetchone()[0] == n_cases + 1
    assert conn.execute('SELECT count(*) FROM "case" WHERE airtable_id=\'recY\'').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM "case" WHERE airtable_id IS NULL').fetchone()[0] >= 1


def test_linking_fills_empty_case_fields_but_keeps_staff_edits(tmp_path):
    conn = _db(tmp_path)
    importer.import_records(conn, importer.read_csv(_csv(tmp_path)))  # case has status 'Нов', no reg no
    api = [{"_id": "recZ", "Име": "Тестов Тест", "Номер паспорт": "XX0000001", "Фирма": "ТЕСТ ЕООД",
            "Позиция": "Общ работник", "Тип виза": "3 години", "Статус": "Подаден",
            "Вх.номер": "777", "Дата на входиране": "2026-05-06"}]
    importer.import_records(conn, api)
    row = conn.execute('SELECT status, reg_no, reg_date FROM "case" WHERE airtable_id=\'recZ\'').fetchone()
    assert row["reg_no"] == "777" and row["reg_date"] == "2026-05-06"  # empty fields filled
    assert row["status"] == "Нов"  # existing value kept
