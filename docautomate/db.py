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
    master_key TEXT UNIQUE,                -- manifest file name of a shipped master; never changes
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


VISA_TYPES = ("1 година", "3 години", "3 месеца", "Удължаване")

# The seven attachment fields of a worker (задание, раздел 02) and the employer's one.
WORKER_ATTACHMENTS = (
    ("passport", "Паспорт и свидетелство за съдимост"),
    ("documents", "Документи"),
    ("nap", "НАП"),
    ("visa_interview", "Документи интервю виза"),
    ("permit", "Разрешение Миграция"),
    ("insurance", "Медицинска застраховка"),
    ("invitation", "Invitation Letter"),
)
EMPLOYER_ATTACHMENTS = (("company", "Фирмени документи"),)

# Unique record numbers start here and never go back, even after a delete.
REF_START = {"worker": 1001, "employer": 101}

STAGE1_SCHEMA = """
CREATE TABLE IF NOT EXISTS employer_address (
    id INTEGER PRIMARY KEY,
    employer_id INTEGER NOT NULL REFERENCES employer(id) ON DELETE CASCADE,
    address TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_employer_address_employer ON employer_address(employer_id);

CREATE TABLE IF NOT EXISTS attachment (
    id INTEGER PRIMARY KEY,
    owner_type TEXT NOT NULL CHECK (owner_type IN ('worker', 'employer')),
    owner_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,      -- under data/attachments/
    original_name TEXT NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_attachment_owner ON attachment(owner_type, owner_id);

CREATE TABLE IF NOT EXISTS ref_counter (
    kind TEXT PRIMARY KEY,
    last_value INTEGER NOT NULL
);

-- Every manual status change: before, after, when, by whom (задание раздел 03).
CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL,         -- kept after the worker is deleted
    old_status TEXT NOT NULL DEFAULT '',
    new_status TEXT NOT NULL,
    changed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    changed_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_status_history_candidate ON status_history(candidate_id);
"""

# Columns added after v1. ALTER TABLE keeps existing databases and their data.
_ADDED_COLUMNS = {
    "candidate": [
        ("ref_no", "INTEGER"),
        ("employer_id", "INTEGER REFERENCES employer(id) ON DELETE RESTRICT"),
        ("position_id", "INTEGER REFERENCES position(id) ON DELETE SET NULL"),
        ("workplace_address", "TEXT NOT NULL DEFAULT ''"),
        ("residence_address", "TEXT NOT NULL DEFAULT ''"),
        ("visa_type", "TEXT NOT NULL DEFAULT ''"),
        ("contact", "TEXT NOT NULL DEFAULT ''"),
        # Справки (График), задание раздел 03
        ("in_no", "TEXT NOT NULL DEFAULT ''"),
        ("filed_date", "TEXT"),
        ("permit_date", "TEXT"),
        ("visa_interview_date", "TEXT"),
        ("visa_date", "TEXT"),
        ("ticket_date", "TEXT"),
        ("arrival_date", "TEXT"),
        ("migration_reg_date", "TEXT"),
        ("lk_submit_date", "TEXT"),
        ("lk_pickup_date", "TEXT"),
        ("residence_until", "TEXT"),
        ("status_changed_at", "TEXT"),
    ],
    "employer": [
        ("ref_no", "INTEGER"),
    ],
}


def next_ref(conn: sqlite3.Connection, kind: str) -> int:
    """Next permanent record number for 'worker' or 'employer'. Never reused."""
    table = "candidate" if kind == "worker" else "employer"
    conn.execute("INSERT OR IGNORE INTO ref_counter (kind, last_value) VALUES (?,?)", (kind, REF_START[kind] - 1))
    conn.execute(f"UPDATE ref_counter SET last_value=max(last_value, coalesce((SELECT max(ref_no) FROM {table}), 0))"
                 " + 1 WHERE kind=?", (kind,))
    return conn.execute("SELECT last_value FROM ref_counter WHERE kind=?", (kind,)).fetchone()[0]


# Any insert path (forms, Airtable import, tests) gets its number from the same counter.
_REF_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS trg_{table}_ref AFTER INSERT ON {table} WHEN NEW.ref_no IS NULL BEGIN
    INSERT OR IGNORE INTO ref_counter (kind, last_value) VALUES ('{kind}', {start});
    UPDATE ref_counter SET last_value=max(last_value, coalesce((SELECT max(ref_no) FROM {table}), 0)) + 1
        WHERE kind='{kind}';
    UPDATE {table} SET ref_no=(SELECT last_value FROM ref_counter WHERE kind='{kind}') WHERE id=NEW.id;
END;
"""


def _visa_type_for(case_type_name: str, residence_period: str, is_extension: int) -> str:
    if is_extension:
        return "Удължаване"
    for v in VISA_TYPES:
        if v in (residence_period or "") or v in (case_type_name or ""):
            return v
    return ""


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring databases created by older versions up to the current schema."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(doc_template)")}
    if "master_key" not in cols:
        conn.execute("ALTER TABLE doc_template ADD COLUMN master_key TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_template_master_key ON doc_template(master_key)")
        # existing master rows get their key in app.install_masters (matched by file or name)

    conn.executescript(STAGE1_SCHEMA)
    added = set()
    for table, columns in _ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                added.add((table, name))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_ref ON candidate(ref_no)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_employer_ref ON employer(ref_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_candidate_employer ON candidate(employer_id)")

    # Every record gets its permanent number, in the order it was created.
    for kind, table in (("employer", "employer"), ("worker", "candidate")):
        for (rid,) in conn.execute(f"SELECT id FROM {table} WHERE ref_no IS NULL ORDER BY id").fetchall():
            conn.execute(f"UPDATE {table} SET ref_no=? WHERE id=?", (next_ref(conn, kind), rid))
        conn.executescript(_REF_TRIGGERS.format(table=table, kind=kind, start=REF_START[kind] - 1))
    # Every new worker starts as „Нов“ and its status clock starts at creation, whatever the insert path.
    conn.executescript("""
CREATE TRIGGER IF NOT EXISTS trg_candidate_status AFTER INSERT ON candidate
WHEN NEW.status='' OR NEW.status_changed_at IS NULL BEGIN
    UPDATE candidate SET status=CASE WHEN status='' THEN 'Нов' ELSE status END,
                         status_changed_at=coalesce(status_changed_at, created_at) WHERE id=NEW.id;
END;
""")

    if ("candidate", "status_changed_at") in added:
        # Statuses from before the График: keep known ones, start the rest as „Нов“ counted from creation.
        from .schedule import ALL_STATUSES
        marks = ",".join("?" * len(ALL_STATUSES))
        # an unknown old status text is kept in the notes, not lost
        conn.execute("UPDATE candidate SET notes=trim(notes || char(10) || 'Стар статус: ' || status)"
                     f" WHERE status<>'' AND status NOT IN ({marks})", ALL_STATUSES)
        conn.execute(f"UPDATE candidate SET status='Нов' WHERE status NOT IN ({marks})", ALL_STATUSES)
        conn.execute("UPDATE candidate SET status_changed_at=CASE WHEN status='Нов' THEN created_at"
                     " ELSE updated_at END")

    if ("candidate", "employer_id") in added:
        # Before, employer, position and case type lived only on the case. Copy them from each
        # worker's newest case so nothing has to be re-entered.
        for r in conn.execute(
                'SELECT c.candidate_id, c.employer_id, c.position_id, ct.name, ct.residence_period, ct.is_extension'
                ' FROM "case" c JOIN case_type ct ON ct.id=c.case_type_id'
                ' WHERE c.id IN (SELECT max(id) FROM "case" GROUP BY candidate_id)').fetchall():
            conn.execute("UPDATE candidate SET employer_id=?, position_id=?, visa_type=? WHERE id=?",
                         (r[1], r[2], _visa_type_for(r[3], r[4], r[5]), r[0]))
        # Work addresses: one per distinct position workplace, so the new dropdown is not empty.
        for eid, addr in conn.execute(
                "SELECT DISTINCT employer_id, trim(workplace) FROM position WHERE trim(workplace)<>''").fetchall():
            if not conn.execute("SELECT 1 FROM employer_address WHERE employer_id=? AND address=?",
                                (eid, addr)).fetchone():
                conn.execute("INSERT INTO employer_address (employer_id, address) VALUES (?,?)", (eid, addr))
        conn.execute(
            "UPDATE candidate SET workplace_address=coalesce((SELECT trim(p.workplace) FROM position p"
            " WHERE p.id=candidate.position_id), '') WHERE position_id IS NOT NULL AND workplace_address=''")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
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
        names |= {a.strip().lower() for a in row["aliases"].split(",") if a.strip()}
        if t in names:
            return row
    return None
