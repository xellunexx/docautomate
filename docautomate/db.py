"""SQLite storage. One file, no server: data/docautomate.db next to the app."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g

from .countries import COUNTRIES

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS country (
    id INTEGER PRIMARY KEY,
    iso3 TEXT UNIQUE,
    name TEXT NOT NULL UNIQUE,             -- short: Узбекистан
    name_official TEXT NOT NULL DEFAULT '',-- Република Узбекистан
    name_ru_gen TEXT NOT NULL DEFAULT '',  -- Республики Узбекистан
    name_ru_instr TEXT NOT NULL DEFAULT '',-- Республикой Узбекистан
    aliases TEXT NOT NULL DEFAULT ''       -- comma separated, lower case
);

CREATE TABLE IF NOT EXISTS employer (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    eik TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    rep_name TEXT NOT NULL DEFAULT '',
    rep_role TEXT NOT NULL DEFAULT 'управител',
    rep_gender TEXT NOT NULL DEFAULT '' CHECK (rep_gender IN ('', 'M', 'F')),
    rep_egn TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS position (
    id INTEGER PRIMARY KEY,
    employer_id INTEGER NOT NULL REFERENCES employer(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    title_ru TEXT NOT NULL DEFAULT '',
    nkpd TEXT NOT NULL DEFAULT '',
    occupation_class TEXT NOT NULL DEFAULT '',
    workplace TEXT NOT NULL DEFAULT '',
    reporting_line TEXT NOT NULL DEFAULT '',
    obosnovka TEXT NOT NULL DEFAULT '',
    dh_purpose TEXT NOT NULL DEFAULT '',
    dh_duties TEXT NOT NULL DEFAULT '',
    dh_responsibilities TEXT NOT NULL DEFAULT '',
    dh_rights TEXT NOT NULL DEFAULT '',
    dh_requirements TEXT NOT NULL DEFAULT '',
    dh_conditions TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (employer_id, title)
);
CREATE INDEX IF NOT EXISTS ix_position_employer ON position(employer_id);

CREATE TABLE IF NOT EXISTS candidate (
    id INTEGER PRIMARY KEY,
    name_cyr TEXT NOT NULL DEFAULT '',
    name_lat TEXT NOT NULL DEFAULT '',
    gender TEXT NOT NULL DEFAULT '' CHECK (gender IN ('', 'M', 'F')),
    birth_date TEXT,
    birth_place TEXT NOT NULL DEFAULT '',
    birth_country_id INTEGER REFERENCES country(id),
    citizenship_id INTEGER REFERENCES country(id),
    passport_no TEXT NOT NULL DEFAULT '',
    passport_issue_date TEXT,
    passport_expiry TEXT,
    passport_issued_by TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    lnch TEXT NOT NULL DEFAULT '',
    address_bg TEXT NOT NULL DEFAULT '',
    marital_status TEXT NOT NULL DEFAULT '',
    education TEXT NOT NULL DEFAULT '',
    specialty TEXT NOT NULL DEFAULT '',
    qualification TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    passport_scan TEXT NOT NULL DEFAULT '',
    airtable_id TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_candidate_passport ON candidate(passport_no);

CREATE TABLE IF NOT EXISTS case_type (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    legal_ground TEXT NOT NULL DEFAULT '',
    residence_period TEXT NOT NULL DEFAULT '',
    is_extension INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS doc_template (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT NOT NULL UNIQUE,         -- stored under data/templates/
    is_master INTEGER NOT NULL DEFAULT 0,  -- shipped with the app
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100,
    placeholders TEXT NOT NULL DEFAULT '',
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS case_type_template (
    case_type_id INTEGER NOT NULL REFERENCES case_type(id) ON DELETE CASCADE,
    template_id INTEGER NOT NULL REFERENCES doc_template(id) ON DELETE CASCADE,
    PRIMARY KEY (case_type_id, template_id)
);

CREATE TABLE IF NOT EXISTS "case" (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidate(id) ON DELETE RESTRICT,
    employer_id INTEGER NOT NULL REFERENCES employer(id) ON DELETE RESTRICT,
    position_id INTEGER REFERENCES position(id) ON DELETE RESTRICT,
    case_type_id INTEGER NOT NULL REFERENCES case_type(id) ON DELETE RESTRICT,
    copied_from_id INTEGER REFERENCES "case"(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT '',
    contract_months INTEGER,
    probation_months INTEGER,
    salary TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'евро',
    pay_day TEXT NOT NULL DEFAULT '30',
    leave_days INTEGER,
    extra_leave_days INTEGER,
    notice_months INTEGER,
    working_time TEXT NOT NULL DEFAULT '',
    contract_extension INTEGER NOT NULL DEFAULT 0,
    contract_no TEXT NOT NULL DEFAULT '',
    contract_date TEXT,
    start_date TEXT,
    directorate TEXT NOT NULL DEFAULT '',
    notification_email TEXT NOT NULL DEFAULT '',
    staff_count TEXT NOT NULL DEFAULT '',
    foreign_staff_count TEXT NOT NULL DEFAULT '',
    doc_city TEXT NOT NULL DEFAULT '',
    doc_date TEXT,
    reg_no TEXT NOT NULL DEFAULT '',
    reg_date TEXT,
    notes TEXT NOT NULL DEFAULT '',
    airtable_id TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_case_candidate ON "case"(candidate_id);
CREATE INDEX IF NOT EXISTS ix_case_employer ON "case"(employer_id);

CREATE TABLE IF NOT EXISTS generation (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES "case"(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    folder TEXT NOT NULL,                  -- under data/generated/
    snapshot TEXT NOT NULL DEFAULT ''      -- JSON of the data used
);
CREATE INDEX IF NOT EXISTS ix_generation_case ON generation(case_id);

CREATE TABLE IF NOT EXISTS generated_file (
    id INTEGER PRIMARY KEY,
    generation_id INTEGER NOT NULL REFERENCES generation(id) ON DELETE CASCADE,
    template_name TEXT NOT NULL,
    pdf_name TEXT NOT NULL DEFAULT '',
    docx_name TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT ''
);
"""

DEFAULT_CASE_TYPES = [
    # name, legal ground, residence period, is_extension, sort
    ("Единно разрешение – 3 години (чл. 24и)", "24и", "3 години", 0, 10),
    ("Виза 3 месеца", "", "3 месеца", 0, 20),
    ("Удължаване", "24и", "3 години", 1, 30),
]


def data_dir() -> Path:
    return Path(current_app.config["DATA_DIR"])


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, detect_types=0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(Path(current_app.config["DATABASE"]))
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for iso3, name, official, ru_gen, ru_instr, aliases in COUNTRIES:
        conn.execute(
            "INSERT OR IGNORE INTO country (iso3, name, name_official, name_ru_gen, name_ru_instr, aliases)"
            " VALUES (?,?,?,?,?,?)",
            (iso3, name, official, ru_gen, ru_instr, ",".join(aliases)),
        )
    for name, ground, period, ext, sort in DEFAULT_CASE_TYPES:
        conn.execute(
            "INSERT OR IGNORE INTO case_type (name, legal_ground, residence_period, is_extension, sort_order)"
            " VALUES (?,?,?,?,?)",
            (name, ground, period, ext, sort),
        )
    conn.commit()


def find_country(conn: sqlite3.Connection, text: str | None):
    """Match a country by ISO3, short name, official name or alias (case-insensitive, trimmed)."""
    if not text:
        return None
    t = text.strip().lower()
    if not t:
        return None
    for row in conn.execute("SELECT * FROM country"):
        names = {row["name"].lower(), row["name_official"].lower(), (row["iso3"] or "").lower()}
        names |= {a.strip() for a in row["aliases"].split(",") if a.strip()}
        if t in names:
            return row
    return None
