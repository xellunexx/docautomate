"""Builds the data a template sees: {{ candidate.* }}, {{ employer.* }}, {{ position.* }}, {{ case.* }}.

The list of placeholders shown to staff (PLACEHOLDERS) is the single source of truth: the
context builder must produce exactly these keys, and a test checks that.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3

from . import grammar


class Blank(str):
    """An empty value that prints as a dotted line (like the paper forms) but is falsy,
    so `{% if candidate.lnch %}` still works in templates."""

    DOTS = "……………………"

    def __new__(cls):
        return super().__new__(cls, cls.DOTS)

    def __bool__(self):
        return False


def _v(value):
    """Normalise a value for templates: None/'' -> Blank()."""
    if value is None:
        return Blank()
    if isinstance(value, str) and not value.strip():
        return Blank()
    return value


def _lines(text: str | None) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _paragraphs(text: str | None) -> list[str]:
    """Split prose on blank lines (or single newlines) into paragraphs."""
    return _lines(text)


# dotted key -> (label in Bulgarian, example)
PLACEHOLDERS: dict[str, tuple[str, str]] = {
    # candidate
    "candidate.name_cyr": ("Имена на кирилица", "Иванов Петър Сергеевич"),
    "candidate.name_lat": ("Имена на латиница (по паспорт)", "Ivanov Petr Sergeevich"),
    "candidate.names": ("Кирилица / латиница", "Иванов Петър Сергеевич/ Ivanov Petr Sergeevich"),
    "candidate.gender": ("Пол (M/F)", "M"),
    "candidate.female": ("Истина, ако е жена (за {% if %})", "False"),
    "candidate.title": ("г-н / г-жа", "г-н"),
    "candidate.title_full": ("господин / госпожа", "господин"),
    "candidate.roden": ("роден / родена", "роден"),
    "candidate.grazhdanin": ("гражданин / гражданка", "гражданин"),
    "candidate.naritsan": ("наричан / наричана", "наричан"),
    "candidate.dolupodpisan": ("долуподписаният / долуподписаната", "долуподписаният"),
    "candidate.rabotnik": ("работник / работничка", "работник"),
    "candidate.ru_grazhdanin": ("RU: гражданин / гражданка", "гражданин"),
    "candidate.ru_rodilsya": ("RU: родился / родилась", "родился"),
    "candidate.ru_imenuemyi": ("RU: именуемый / именуемая", "именуемый"),
    "candidate.en_title": ("EN: Mr / Ms", "Mr"),
    "candidate.en_he": ("EN: he / she", "he"),
    "candidate.en_him": ("EN: him / her", "him"),
    "candidate.en_his": ("EN: his / her", "his"),
    "candidate.ref_no": ("Уникален номер на работника", "1001"),
    "candidate.birth_date": ("Дата на раждане", "01.01.1985"),
    "candidate.birth_place": ("Място на раждане", "Tashkent"),
    "candidate.birth_country": ("Държава на раждане (официално име)", "Република Узбекистан"),
    "candidate.citizenship": ("Гражданство (официално име)", "Република Узбекистан"),
    "candidate.citizenship_short": ("Гражданство (кратко)", "Узбекистан"),
    "candidate.citizenship_ru_gen": ("RU: гражданство, род. падеж", "Республики Узбекистан"),
    "candidate.citizenship_ru_instr": ("RU: гражданство, твор. падеж", "Республикой Узбекистан"),
    "candidate.citizenship_en": ("EN: гражданство (официално име)", "Republic of Uzbekistan"),
    "candidate.embassy": ("Посолство за виза D (Invitation Letter)", "New Delhi, India"),
    "candidate.passport_no": ("Паспорт №", "AB1234567"),
    "candidate.passport_issue_date": ("Паспорт издаден на", "15.03.2020"),
    "candidate.passport_expiry": ("Паспорт валиден до", "14.03.2030"),
    "candidate.passport_issued_by": ("Паспорт издаден от", "Република Узбекистан"),
    "candidate.phone": ("Телефон", "0888123456"),
    "candidate.lnch": ("ЛНЧ", "1000000000"),
    "candidate.address_bg": ("Адрес в България", "гр. София, ул. Примерна 1"),
    "candidate.residence_address": ("Адрес на местоживеене (декларация за жилище)", "гр. София, ж.к. Примерен, бл. 1"),
    "candidate.marital_status": ("Семейно положение", "неженен"),
    "candidate.education": ("Образование", "средно"),
    "candidate.specialty": ("Специалност", ""),
    "candidate.qualification": ("Квалификация", ""),
    # employer
    "employer.name": ("Фирма", "ПРИМЕР ЕООД"),
    "employer.eik": ("ЕИК", "200000000"),
    "employer.address": ("Седалище и адрес на управление", "гр. София, ул. Примерна 10"),
    "employer.rep_name": ("Представляващ – имена", "Георги Иванов Петров"),
    "employer.rep_role": ("Представляващ – длъжност", "управител"),
    "employer.rep_egn": ("Представляващ – ЕГН", "0000000000"),
    "employer.rep_title": ("Представляващ – г-н / г-жа", "г-н"),
    "employer.rep_dolupodpisan": ("Долуподписаният / Долуподписаната", "Долуподписаният"),
    "employer.rep_v_kachestvoto": ("в качеството му / в качеството ѝ", "в качеството му"),
    "employer.phone": ("Телефон на фирмата", "+359888000000"),
    "employer.email": ("Е-поща на фирмата", "office@example.bg"),
    # position
    "position.title": ("Длъжност", "Общ работник"),
    "position.title_ru": ("Длъжност на руски (ако няма – българската)", "Подсобный рабочий"),
    "position.nkpd": ("Код по НКПД", "96220001"),
    "position.occupation_class": ("Клас професии", "неквалифицирани работници"),
    "employer.workplace": ("Адрес на месторабота на фирмата (първият от профила; ако няма – седалището)",
                           "гр. София, ул. Работна 5"),
    "position.workplace": ("Място на работа (на работника; ако няма – на длъжността, на фирмата, седалището)",
                           "гр. София, ул. Работна 5"),
    "position.reporting_line": ("Пряко подчинение", "Управителя"),
    "position.obosnovka": ("Обосновка – целият текст (при удължаване – текстът за удължаване, ако има)", "…"),
    "position.obosnovka_paragraphs": ("Обосновка – списък абзаци (за {%p for %})", "[…]"),
    "position.dh_purpose": ("ДХ: основна цел", "…"),
    "position.dh_duties": ("ДХ: задължения – списък (по ред)", "[…]"),
    "position.dh_responsibilities": ("ДХ: отговорности – списък", "[…]"),
    "position.dh_rights": ("ДХ: права – списък", "[…]"),
    "position.dh_requirements": ("ДХ: изисквания – списък", "[…]"),
    "position.dh_conditions": ("ДХ: условия на труд – списък абзаци", "[…]"),
    # case
    "case.type": ("Вид случай", "Единно разрешение – 3 години (чл. 24и)"),
    "case.legal_ground": ("Правно основание", "24и"),
    "case.is_extension": ("Истина при удължаване (за {% if %})", "False"),
    "case.residence_period": ("Срок на пребиваване", "3 години"),
    "case.contract_months": ("Срок на договора (месеци)", "36"),
    "case.contract_term": ("Срок на договора (текст)", "3 години"),
    "case.contract_extension": ("Продължение на договор (Да/Не)", "Не"),
    "case.contract_unit": ("месец/месеца за срока", "месеца"),
    "case.probation_months": ("Изпитателен срок (месеци)", "6"),
    "case.probation_unit": ("месец/месеца за изпитателния срок", "месеца"),
    "case.probation_words": ("Изпитателен срок с думи", "шест"),
    "case.probation_words_ru": ("RU: изпитателен срок с думи", "шесть"),
    "case.probation_unit_ru": ("RU: месяц/месяца/месяцев за изпит. срок", "месяцев"),
    "case.contract_unit_ru": ("RU: месяц/месяца/месяцев за срока", "месяцев"),
    "case.contract_unit_en": ("EN: month/months за срока", "months"),
    "case.contract_words_en": ("EN: срок на договора с думи", "thirty-six"),
    "case.probation_words_en": ("EN: изпитателен срок с думи", "six"),
    "case.probation_unit_en": ("EN: month/months за изпитателния срок", "months"),
    "case.notice_words_en": ("EN: предизвестие с думи", "three"),
    "case.notice_unit_en": ("EN: month/months за предизвестието", "months"),
    "case.extra_leave_words_en": ("EN: доп. отпуск с думи", "zero"),
    "case.salary": ("Основно месечно възнаграждение", "1077.00"),
    "case.currency": ("Валута", "евро"),
    "case.pay_day": ("Ден на изплащане", "30"),
    "case.leave_days": ("Платен годишен отпуск (дни)", "20"),
    "case.extra_leave_days": ("Допълнителен отпуск (дни)", "0"),
    "case.extra_leave_words_ru": ("RU: доп. отпуск с думи", "ноль"),
    "case.notice_months": ("Предизвестие (месеци)", "3"),
    "case.notice_words": ("Предизвестие с думи", "три"),
    "case.notice_words_ru": ("RU: предизвестие с думи", "три"),
    "case.notice_unit": ("месец/месеца за предизвестието", "месеца"),
    "case.notice_unit_ru": ("RU: месяц/месяца/месяцев за предизвестието", "месяца"),
    "case.working_time": ("Работно време", "пълно работно време"),
    "case.contract_no": ("№ на трудовия договор", "15"),
    "case.contract_date": ("Дата на трудовия договор", "01.12.2026"),
    "case.start_date": ("Дата на постъпване", ""),
    "case.directorate": ("До директора на", "дирекция „Миграция“"),
    "case.notification_email": ("Е-поща за съобщения", "office@example.bg"),
    "case.staff_count": ("Наети служители (брой)", "25"),
    "case.foreign_staff_count": ("В т.ч. чужденци (брой)", "3"),
    "case.doc_city": ("Град (за документите)", "София"),
    "case.doc_date": ("Дата (за документите)", "01.12.2026"),
    "case.reg_no": ("Вх. № на заявлението", ""),
    "case.reg_date": ("Дата на входиране", ""),
    "today": ("Днешна дата", "26.11.2026"),
    "housing_workers": ("Декларация по чл. 28: работниците на същия адрес – списък", "[…]"),
}

LIST_FIELDS = {
    "housing_workers",
    "position.obosnovka_paragraphs", "position.dh_duties", "position.dh_responsibilities",
    "position.dh_rights", "position.dh_requirements", "position.dh_conditions",
}
BOOL_FIELDS = {"candidate.female", "case.is_extension"}


def _country(conn, cid):
    if not cid:
        return None
    return conn.execute("SELECT * FROM country WHERE id=?", (cid,)).fetchone()


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build_context(conn: sqlite3.Connection, case_id: int) -> dict:
    case = conn.execute('SELECT * FROM "case" WHERE id=?', (case_id,)).fetchone()
    if case is None:
        raise LookupError(f"Няма случай №{case_id}")
    cand = conn.execute("SELECT * FROM candidate WHERE id=?", (case["candidate_id"],)).fetchone()
    emp = dict(conn.execute("SELECT * FROM employer WHERE id=?", (case["employer_id"],)).fetchone())
    first = conn.execute("SELECT address FROM employer_address WHERE employer_id=? ORDER BY sort_order, id LIMIT 1",
                         (case["employer_id"],)).fetchone()
    emp["workplace"] = first["address"] if first else ""
    pos = conn.execute("SELECT * FROM position WHERE id=?", (case["position_id"],)).fetchone() \
        if case["position_id"] else None
    ctype = conn.execute("SELECT * FROM case_type WHERE id=?", (case["case_type_id"],)).fetchone()
    ctx = assemble(dict(cand), emp, dict(pos) if pos else {}, dict(case), dict(ctype),
                   _country(conn, cand["citizenship_id"]), _country(conn, cand["birth_country_id"]))
    ctx["housing_workers"] = housing_workers(conn, cand)
    return ctx


def housing_workers(conn, cand) -> list[str]:
    """Workers for the seasonal housing declaration (чл. 28 ЗТМТМ): this worker plus the other workers of
    the same employer, with the same visa type, living at the same address. Names as „кирилица/ латиница“."""
    rows = [cand]
    addr = (cand["residence_address"] or "").strip()
    if addr and cand["employer_id"]:
        rows += conn.execute(
            "SELECT * FROM candidate WHERE employer_id=? AND visa_type=? AND trim(residence_address)=? AND id<>?"
            " ORDER BY name_cyr", (cand["employer_id"], cand["visa_type"] or "", addr, cand["id"])).fetchall()
    return ["/ ".join(x for x in (r["name_cyr"], r["name_lat"]) if x) for r in rows]


def assemble(cand: dict, emp: dict, pos: dict, case: dict, ctype: dict,
             citizenship=None, birth_country=None, today: _dt.date | None = None) -> dict:
    """Pure function: rows -> template context. Kept separate so tests need no database."""
    today = today or _dt.date.today()
    g = cand.get("gender") or ""
    cforms = grammar.gender_forms(g, grammar.CANDIDATE_FORMS)
    rforms = grammar.gender_forms(emp.get("rep_gender") or "", grammar.REPRESENTATIVE_FORMS)
    if not emp.get("rep_gender"):
        rforms["v_kachestvoto"] = "в качеството си"  # correct for both genders
    cit = dict(citizenship) if citizenship else {}
    bc = dict(birth_country) if birth_country else {}

    candidate = {
        "name_cyr": cand.get("name_cyr"),
        "name_lat": cand.get("name_lat"),
        "names": "/ ".join(x for x in (cand.get("name_cyr"), cand.get("name_lat")) if x),
        "gender": g,
        "female": g == "F",
        **cforms,
        "birth_date": grammar.fmt_date(cand.get("birth_date")),
        "birth_place": cand.get("birth_place"),
        "birth_country": bc.get("name_official") or bc.get("name"),
        "citizenship": cit.get("name_official") or cit.get("name"),
        "citizenship_short": cit.get("name"),
        "citizenship_ru_gen": cit.get("name_ru_gen"),
        "citizenship_ru_instr": cit.get("name_ru_instr"),
        "citizenship_en": cit.get("name_en"),
        "embassy": cit.get("embassy"),
        "ref_no": cand.get("ref_no"),
        "residence_address": cand.get("residence_address"),
        "passport_no": cand.get("passport_no"),
        "passport_issue_date": grammar.fmt_date(cand.get("passport_issue_date")),
        "passport_expiry": grammar.fmt_date(cand.get("passport_expiry")),
        "passport_issued_by": cand.get("passport_issued_by") or cit.get("name_official"),
        "phone": cand.get("phone"),
        "lnch": cand.get("lnch"),
        "address_bg": cand.get("address_bg"),
        "marital_status": cand.get("marital_status"),
        "education": cand.get("education"),
        "specialty": cand.get("specialty"),
        "qualification": cand.get("qualification"),
    }
    employer = {
        "name": emp.get("name"),
        "eik": emp.get("eik"),
        "address": emp.get("address"),
        "workplace": emp.get("workplace") or emp.get("address"),
        "rep_name": emp.get("rep_name"),
        "rep_role": emp.get("rep_role"),
        "rep_egn": emp.get("rep_egn"),
        "rep_title": rforms["title"],
        "rep_dolupodpisan": rforms["dolupodpisan"],
        "rep_v_kachestvoto": rforms["v_kachestvoto"],
        "phone": emp.get("phone"),
        "email": emp.get("email"),
    }
    # Extensions have their own justification order (задание 04); fall back to the initial text.
    obosnovka = (pos.get("obosnovka_ext") if ctype.get("is_extension") else None) or pos.get("obosnovka")
    position = {
        "title": pos.get("title"),
        "title_ru": pos.get("title_ru") or pos.get("title"),
        "nkpd": pos.get("nkpd"),
        "occupation_class": pos.get("occupation_class"),
        # where the work is done: the worker's address, else the position's, else the employer's, else the seat
        "workplace": cand.get("workplace_address") or pos.get("workplace") or emp.get("workplace") or emp.get("address"),
        "reporting_line": pos.get("reporting_line"),
        "obosnovka": obosnovka,
        "obosnovka_paragraphs": _paragraphs(obosnovka),
        "dh_purpose": pos.get("dh_purpose"),
        "dh_duties": _lines(pos.get("dh_duties")),
        "dh_responsibilities": _lines(pos.get("dh_responsibilities")),
        "dh_rights": _lines(pos.get("dh_rights")),
        "dh_requirements": _lines(pos.get("dh_requirements")),
        "dh_conditions": _paragraphs(pos.get("dh_conditions")),
    }
    cm = _int(case.get("contract_months"))
    pm = _int(case.get("probation_months"))
    nm = _int(case.get("notice_months"))
    xl = _int(case.get("extra_leave_days"))
    case_ctx = {
        "type": ctype.get("name"),
        "legal_ground": ctype.get("legal_ground"),
        "is_extension": bool(ctype.get("is_extension")),
        "residence_period": ctype.get("residence_period"),
        "contract_months": cm,
        "contract_term": grammar.term_text_bg(cm),
        "contract_unit": grammar.months_bg(cm) if cm is not None else None,
        "probation_unit": grammar.months_bg(pm) if pm is not None else None,
        "notice_unit": grammar.months_bg(nm) if nm is not None else None,
        "notice_unit_ru": grammar.months_ru(nm) if nm is not None else None,
        "contract_extension": "Да" if case.get("contract_extension") else "Не",
        "probation_months": pm,
        "probation_words": grammar.words_bg(pm) if pm is not None else None,
        "probation_words_ru": grammar.words_ru(pm) if pm is not None else None,
        "probation_unit_ru": grammar.months_ru(pm) if pm is not None else None,
        "contract_unit_ru": grammar.months_ru(cm) if cm is not None else None,
        "contract_unit_en": grammar.months_en(cm) if cm is not None else None,
        "contract_words_en": grammar.words_en(cm) if cm is not None else None,
        "probation_words_en": grammar.words_en(pm) if pm is not None else None,
        "probation_unit_en": grammar.months_en(pm) if pm is not None else None,
        "notice_words_en": grammar.words_en(nm) if nm is not None else None,
        "notice_unit_en": grammar.months_en(nm) if nm is not None else None,
        "extra_leave_words_en": grammar.words_en(xl) if xl is not None else None,
        "salary": grammar.fmt_money(case.get("salary")),
        "currency": case.get("currency"),
        "pay_day": case.get("pay_day"),
        "leave_days": _int(case.get("leave_days")),
        "extra_leave_days": xl,
        "extra_leave_words_ru": grammar.words_ru(xl) if xl is not None else None,
        "notice_months": nm,
        "notice_words": grammar.words_bg(nm) if nm is not None else None,
        "notice_words_ru": grammar.words_ru(nm) if nm is not None else None,
        "working_time": case.get("working_time"),
        "contract_no": case.get("contract_no"),
        "contract_date": grammar.fmt_date(case.get("contract_date")),
        "start_date": grammar.fmt_date(case.get("start_date")),
        "directorate": case.get("directorate"),
        "notification_email": case.get("notification_email"),
        "staff_count": case.get("staff_count"),
        "foreign_staff_count": case.get("foreign_staff_count"),
        "doc_city": case.get("doc_city"),
        "doc_date": grammar.fmt_date(case.get("doc_date")),
        # the incoming number and filing date live in the График now; a value typed on the case wins
        "reg_no": case.get("reg_no") or cand.get("in_no"),
        "reg_date": grammar.fmt_date(case.get("reg_date") or cand.get("filed_date")),
    }

    def norm(d):
        return {k: (v if isinstance(v, (bool, list)) else _v(v)) for k, v in d.items()}

    return {
        "candidate": norm(candidate),
        "employer": norm(employer),
        "position": norm(position),
        "case": norm(case_ctx),
        "today": today.strftime("%d.%m.%Y"),
        "housing_workers": [candidate["names"]] if candidate["names"] else [],
    }


def flatten(ctx: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in ctx.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def missing_fields(ctx: dict, used: set[str]) -> list[str]:
    """Dotted keys used by a template whose value is empty."""
    flat = flatten(ctx)
    out = []
    for key in sorted(used):
        if key in BOOL_FIELDS:
            continue
        v = flat.get(key)
        if v is None or isinstance(v, Blank) or (isinstance(v, list) and not v):
            out.append(key)
    return out


def sample_context() -> dict:
    """Fake data used to validate uploaded templates (never real people)."""
    cand = {
        "name_cyr": "Иванов Петър Сергеевич", "name_lat": "Ivanov Petr Sergeevich", "gender": "M",
        "birth_date": "1985-01-01", "birth_place": "Tashkent", "passport_no": "AB1234567",
        "passport_issue_date": "2020-03-15", "passport_expiry": "2030-03-14", "phone": "0888123456",
        "lnch": "", "address_bg": "", "marital_status": "", "education": "", "specialty": "",
        "qualification": "", "residence_address": "гр. София, ж.к. Примерен, бл. 1", "ref_no": 1001,
    }
    emp = {"name": "ПРИМЕР ЕООД", "eik": "200000000", "address": "гр. София, ул. Примерна 10",
           "workplace": "гр. София, ул. Работна 5",
           "rep_name": "Георги Иванов Петров", "rep_role": "управител", "rep_gender": "M",
           "rep_egn": "0000000000", "phone": "+359888000000", "email": "office@example.bg"}
    pos = {"title": "Общ работник", "nkpd": "96220001", "occupation_class": "неквалифицирани работници",
           "workplace": "гр. София, ул. Работна 5", "reporting_line": "Управителя",
           "obosnovka": "Първи абзац.\nВтори абзац.", "dh_purpose": "Цел.", "dh_duties": "Едно\nДве",
           "dh_responsibilities": "Едно", "dh_rights": "Едно", "dh_requirements": "Едно",
           "dh_conditions": "Абзац."}
    case = {"contract_months": 36, "probation_months": 6, "salary": "1077", "currency": "евро",
            "pay_day": "30", "leave_days": 20, "extra_leave_days": 0, "notice_months": 3,
            "working_time": "пълно работно време", "doc_city": "София", "doc_date": "2026-12-01"}
    ctype = {"name": "Единно разрешение – 3 години (чл. 24и)", "legal_ground": "24и",
             "residence_period": "3 години", "is_extension": 0}
    uzb = {"name": "Узбекистан", "name_official": "Република Узбекистан",
           "name_ru_gen": "Республики Узбекистан", "name_ru_instr": "Республикой Узбекистан",
           "name_en": "Republic of Uzbekistan", "embassy": "Tashkent, Uzbekistan"}
    return assemble(cand, emp, pos, case, ctype, uzb, uzb)
