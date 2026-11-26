"""One-time import of the Airtable "Candidates" table.

Two sources:
  * Airtable API (run on the office PC; the token is read from the AIRTABLE_TOKEN
    environment variable and never stored):
        python -m docautomate.importer --airtable
  * A CSV file exported from Airtable (Grid view -> Download CSV):
        python -m docautomate.importer --csv Candidates.csv

Re-running is safe: records are matched by Airtable id (API) or by passport number /
name + date of birth (CSV), and only *empty* fields are filled, so edits made in the
app are never overwritten.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE = "appLalp0CKbGGFVEO"
DEFAULT_TABLE = "tblDlRvBuAEOMjBDD"  # Candidates

# Airtable field -> our column
F_NAME_CYR = "Име"
F_NAME_LAT = "Име лат"
F_DOB = "Дата на раждане"
F_PASSPORT = "Номер паспорт"
F_COUNTRY = "Държава"
F_EMPLOYER = "Фирма"
F_POSITION = "Позиция"
F_VISA = "Тип виза"
F_STATUS = "Статус"
F_PHONE = "Контакт"
F_REGNO = "Вх.номер"
F_REGDATE = "Дата на входиране"

# Airtable "Тип виза" -> our case type name
VISA_TYPE_MAP = {
    "3 години": "Единно разрешение – 3 години (чл. 24и)",
    "3 месеца": "Виза 3 месеца",
    "удължаване": "Удължаване",
}


@dataclass
class ImportStats:
    candidates_new: int = 0
    candidates_updated: int = 0
    candidates_unchanged: int = 0
    employers_new: int = 0
    positions_new: int = 0
    cases_new: int = 0
    countries_unmatched: dict = field(default_factory=dict)
    skipped: list = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Кандидати: {self.candidates_new} нови, {self.candidates_updated} допълнени, "
            f"{self.candidates_unchanged} без промяна",
            f"Работодатели: {self.employers_new} нови; позиции: {self.positions_new} нови; "
            f"случаи: {self.cases_new} нови",
        ]
        if self.countries_unmatched:
            lines.append("Неразпознати държави (оправете ги в „Държави“): " +
                         ", ".join(f"{k} ({v})" for k, v in self.countries_unmatched.items()))
        if self.skipped:
            lines.append(f"Пропуснати записи: {len(self.skipped)}")
            lines += [f"  - {s}" for s in self.skipped[:20]]
        return "\n".join(lines)


# ---------------------------------------------------------------- sources

def fetch_airtable(token: str, base: str = DEFAULT_BASE, table: str = DEFAULT_TABLE,
                   session=None) -> list[dict]:
    """Read all records via the Airtable Web API (100 per page, 5 req/s limit)."""
    import requests
    s = session or requests.Session()
    url = f"https://api.airtable.com/v0/{base}/{table}"
    headers = {"Authorization": f"Bearer {token}"}
    params: dict = {"pageSize": 100, "cellFormat": "json"}
    out: list[dict] = []
    while True:
        r = s.get(url, headers=headers, params=params, timeout=60)
        if r.status_code == 429:
            time.sleep(30)
            continue
        if r.status_code in (401, 403):
            raise PermissionError("Airtable отказа достъп – проверете токена и правата му (data.records:read).")
        r.raise_for_status()
        data = r.json()
        for rec in data.get("records", []):
            out.append({"_id": rec["id"], **rec.get("fields", {})})
        if not data.get("offset"):
            return out
        params["offset"] = data["offset"]
        time.sleep(0.25)


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in rows]


# ---------------------------------------------------------------- dates

def _detect_day_first(values: list[str]) -> bool:
    """For d/m/y vs m/d/y CSV exports: day-first if any first number > 12."""
    for v in values:
        m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4}).*", v.strip())
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > 12:
                return True
            if b > 12:
                return False
    return True  # Bulgarian default


def to_iso(value, day_first: bool = True) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\.?(?:\s.*)?", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000 if y <= _dt.date.today().year % 100 else 1900
        d, mo = (a, b) if day_first else (b, a)
        try:
            return _dt.date(y, mo, d).isoformat()
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------- import

def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):  # multi-select
        return ", ".join(map(str, v))
    if isinstance(v, dict):
        return str(v.get("name", ""))
    return re.sub(r"\s+", " ", str(v)).strip()


def _get_or_create_employer(conn, name, stats):
    row = conn.execute("SELECT id FROM employer WHERE lower(name)=lower(?)", (name,)).fetchone()
    if row:
        return row["id"]
    stats.employers_new += 1
    return conn.execute("INSERT INTO employer (name) VALUES (?)", (name,)).lastrowid


def _get_or_create_position(conn, employer_id, title, stats):
    row = conn.execute("SELECT id FROM position WHERE employer_id=? AND lower(title)=lower(?)",
                       (employer_id, title)).fetchone()
    if row:
        return row["id"]
    stats.positions_new += 1
    return conn.execute("INSERT INTO position (employer_id, title) VALUES (?,?)",
                        (employer_id, title)).lastrowid


def _case_type_id(conn, visa: str) -> int:
    name = VISA_TYPE_MAP.get(visa.strip().lower(), visa.strip()) if visa else VISA_TYPE_MAP["3 години"]
    row = conn.execute("SELECT id FROM case_type WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO case_type (name, residence_period) VALUES (?,?)", (name, name)).lastrowid


def _find_candidate(conn, rec_id, passport, name, dob, name_lat=""):
    if rec_id:
        row = conn.execute("SELECT * FROM candidate WHERE airtable_id=?", (rec_id,)).fetchone()
        if row:
            return row
    if passport:
        row = conn.execute("SELECT * FROM candidate WHERE upper(passport_no)=upper(?)", (passport,)).fetchone()
        if row:
            return row
    if name and dob:
        return conn.execute("SELECT * FROM candidate WHERE name_cyr=? AND birth_date=?", (name, dob)).fetchone()
    if name and not passport:
        # no passport and no date: only an exact name match with the same gaps counts as the same person
        return conn.execute("SELECT * FROM candidate WHERE name_cyr=? AND passport_no='' AND birth_date IS NULL",
                            (name,)).fetchone()
    if name_lat and not name and not passport:
        # Latin name only: same rules, on the Latin name
        if dob:
            return conn.execute("SELECT * FROM candidate WHERE name_cyr='' AND name_lat=? AND birth_date=?",
                                (name_lat, dob)).fetchone()
        return conn.execute("SELECT * FROM candidate WHERE name_cyr='' AND name_lat=? AND passport_no=''"
                            " AND birth_date IS NULL", (name_lat,)).fetchone()
    return None


def import_records(conn: sqlite3.Connection, records: list[dict], day_first: bool | None = None) -> ImportStats:
    from .db import find_country

    stats = ImportStats()
    if day_first is None:
        day_first = _detect_day_first([_text(r.get(F_DOB)) for r in records] +
                                      [_text(r.get(F_REGDATE)) for r in records])
    for rec in records:
        rec_id = rec.get("_id") or None
        name = _text(rec.get(F_NAME_CYR))
        name_lat = _text(rec.get(F_NAME_LAT))
        passport = _text(rec.get(F_PASSPORT)).replace(" ", "").upper()
        dob = to_iso(_text(rec.get(F_DOB)), day_first)
        if not (name or name_lat or passport):
            stats.skipped.append(f"{rec_id or '?'}: няма име и паспорт")
            continue
        country_txt = _text(rec.get(F_COUNTRY))
        country = find_country(conn, country_txt)
        if country_txt and not country:
            stats.countries_unmatched[country_txt] = stats.countries_unmatched.get(country_txt, 0) + 1

        values = {
            "name_cyr": name, "name_lat": name_lat, "birth_date": dob, "passport_no": passport,
            "citizenship_id": country["id"] if country else None,
            "phone": _text(rec.get(F_PHONE)), "status": _text(rec.get(F_STATUS)),
        }
        existing = _find_candidate(conn, rec_id, passport, name, dob, name_lat)
        if existing is None:
            cols = {k: v for k, v in values.items() if v not in (None, "")}
            if rec_id:
                cols["airtable_id"] = rec_id
            cid = conn.execute(
                f"INSERT INTO candidate ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                list(cols.values()),
            ).lastrowid
            stats.candidates_new += 1
        else:
            cid = existing["id"]
            # fill only empty fields; never overwrite what staff edited in the app
            updates = {k: v for k, v in values.items() if v not in (None, "") and not existing[k]}
            if rec_id and not existing["airtable_id"]:
                updates["airtable_id"] = rec_id
            if updates:
                sets = ", ".join(f"{k}=?" for k in updates)
                conn.execute(f"UPDATE candidate SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
                             [*updates.values(), cid])
                stats.candidates_updated += 1
            else:
                stats.candidates_unchanged += 1

        emp_name = _text(rec.get(F_EMPLOYER))
        if not emp_name:
            continue
        emp_id = _get_or_create_employer(conn, emp_name, stats)
        pos_title = _text(rec.get(F_POSITION))
        pos_id = _get_or_create_position(conn, emp_id, pos_title, stats) if pos_title else None
        ctype = _case_type_id(conn, _text(rec.get(F_VISA)))
        if rec_id:
            dup = conn.execute('SELECT id FROM "case" WHERE airtable_id=?', (rec_id,)).fetchone()
            if not dup:
                # same case imported earlier from CSV (no Airtable id): link it instead of duplicating.
                # Link only when it is clearly the same application: same position and no conflicting
                # registration number. Otherwise the API record is inserted as its own case (nothing dropped).
                reg_no = _text(rec.get(F_REGNO))
                unlinked = conn.execute(
                    'SELECT id FROM "case" WHERE candidate_id=? AND employer_id=? AND case_type_id=?'
                    " AND position_id IS ? AND (reg_no='' OR ?='' OR reg_no=?) AND airtable_id IS NULL",
                    (cid, emp_id, ctype, pos_id, reg_no, reg_no)).fetchall()
                if len(unlinked) == 1:
                    conn.execute('UPDATE "case" SET airtable_id=? WHERE id=?', (rec_id, unlinked[0]["id"]))
                    dup = unlinked[0]
        else:
            dup = conn.execute('SELECT id FROM "case" WHERE candidate_id=? AND employer_id=? AND case_type_id=?',
                               (cid, emp_id, ctype)).fetchone()
        if dup:
            continue
        conn.execute(
            'INSERT INTO "case" (candidate_id, employer_id, position_id, case_type_id, status, reg_no, reg_date,'
            ' contract_months, probation_months, leave_days, extra_leave_days, notice_months, working_time, airtable_id)'
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, emp_id, pos_id, ctype, _text(rec.get(F_STATUS)), _text(rec.get(F_REGNO)),
             to_iso(_text(rec.get(F_REGDATE)), day_first), 36, 6, 20, 0, 3,
             "пълно работно време", rec_id),
        )
        stats.cases_new += 1
    conn.commit()
    return stats


def main(argv=None) -> int:
    from .db import connect, init_db
    from .app import default_data_dir

    p = argparse.ArgumentParser(description="Еднократен импорт на кандидати от Airtable")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=Path, help="CSV файл, свален от Airtable")
    src.add_argument("--airtable", action="store_true", help="чете директно от Airtable (AIRTABLE_TOKEN)")
    p.add_argument("--base", default=os.environ.get("AIRTABLE_BASE", DEFAULT_BASE))
    p.add_argument("--table", default=os.environ.get("AIRTABLE_TABLE", DEFAULT_TABLE))
    p.add_argument("--data-dir", type=Path, default=None)
    args = p.parse_args(argv)

    if args.airtable:
        token = os.environ.get("AIRTABLE_TOKEN", "").strip()
        if not token:
            print("Задайте токена: set AIRTABLE_TOKEN=pat... (не го записвайте във файл)", file=sys.stderr)
            return 2
        records = fetch_airtable(token, args.base, args.table)
    else:
        records = read_csv(args.csv)
    print(f"Прочетени записи: {len(records)}")
    data_dir = args.data_dir or default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(data_dir / "docautomate.db")
    init_db(conn)
    stats = import_records(conn, records)
    print(stats.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
