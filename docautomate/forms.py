"""Form field definitions shared by the HTML forms and the save handlers."""
from __future__ import annotations

from dataclasses import dataclass

from .grammar import parse_date


@dataclass(frozen=True)
class F:
    name: str
    label: str
    kind: str = "text"       # text | textarea | date | int | select | gender | bool | country | email
    required: bool = False
    help: str = ""
    options: tuple = ()
    wide: bool = False


GENDER = (("", "—"), ("M", "мъж"), ("F", "жена"))

CANDIDATE = [
    F("name_cyr", "Имена на кирилица", required=True, help="Както ще се изписват в документите"),
    F("name_lat", "Имена на латиница (по паспорт)"),
    F("gender", "Пол", "gender", help="Нужен за роден/родена, г-н/г-жа"),
    F("birth_date", "Дата на раждане", "date"),
    F("birth_place", "Място на раждане", help="Както е в паспорта, напр. Tashkent Region"),
    F("birth_country_id", "Държава на раждане", "country"),
    F("citizenship_id", "Гражданство", "country"),
    F("passport_no", "Паспорт №"),
    F("passport_issue_date", "Паспорт – издаден на", "date"),
    F("passport_expiry", "Паспорт – валиден до", "date"),
    F("passport_issued_by", "Паспорт – издаден от", help="Празно = държавата на гражданство"),
    F("phone", "Телефон"),
    F("lnch", "ЛНЧ"),
    F("address_bg", "Адрес в България", wide=True),
    F("marital_status", "Семейно положение"),
    F("education", "Образование"),
    F("specialty", "Специалност"),
    F("qualification", "Квалификация"),
    F("status", "Статус"),
    F("notes", "Бележки", "textarea", wide=True),
]

EMPLOYER = [
    F("name", "Фирма (с правната форма, напр. ЕООД)", required=True, wide=True),
    F("eik", "ЕИК"),
    F("address", "Седалище и адрес на управление", wide=True),
    F("rep_name", "Представляващ – три имена"),
    F("rep_role", "Представляващ – длъжност", help="напр. управител"),
    F("rep_gender", "Представляващ – пол", "gender"),
    F("rep_egn", "Представляващ – ЕГН"),
    F("phone", "Телефон"),
    F("email", "Е-поща", "email"),
    F("notes", "Бележки", "textarea", wide=True),
]

POSITION = [
    F("title", "Длъжност", required=True),
    F("title_ru", "Длъжност на руски", help="За руската част на договора. Празно = българската"),
    F("nkpd", "Код по НКПД"),
    F("occupation_class", "Клас професии", help="напр. неквалифицирани работници"),
    F("workplace", "Място на работа (адрес на обекта)", wide=True),
    F("reporting_line", "Пряко подчинение", wide=True),
    F("obosnovka", "Обосновка – текст", "textarea", wide=True,
      help="Всеки ред е отделен абзац. Пише се веднъж за длъжността и се ползва за всички кандидати."),
    F("dh_purpose", "ДХ: I. Основна цел на длъжността", "textarea", wide=True),
    F("dh_duties", "ДХ: II. Основни трудови задължения", "textarea", wide=True, help="По едно на ред"),
    F("dh_responsibilities", "ДХ: III. Отговорности", "textarea", wide=True, help="По една на ред"),
    F("dh_rights", "ДХ: IV. Права", "textarea", wide=True, help="По едно на ред"),
    F("dh_requirements", "ДХ: V. Изисквания за заемане на длъжността", "textarea", wide=True, help="По едно на ред"),
    F("dh_conditions", "ДХ: VI. Условия на труд", "textarea", wide=True, help="Всеки ред е абзац"),
]

CASE = [
    F("contract_months", "Срок на договора (месеци)", "int"),
    F("probation_months", "Изпитателен срок (месеци)", "int"),
    F("salary", "Основно месечно възнаграждение"),
    F("currency", "Валута"),
    F("pay_day", "Изплаща се до (число от месеца)"),
    F("leave_days", "Платен годишен отпуск (дни)", "int"),
    F("extra_leave_days", "Допълнителен платен отпуск (дни)", "int"),
    F("notice_months", "Предизвестие (месеци)", "int"),
    F("working_time", "Работно време", wide=True,
      help="Само за бланки с поле case.working_time. В основния трудов договор текстът е фиксиран (BG и RU)."),
    F("contract_extension", "Продължение на договор", "bool"),
    F("contract_no", "№ на трудовия договор"),
    F("contract_date", "Дата на трудовия договор", "date"),
    F("start_date", "Дата на постъпване", "date"),
    F("directorate", "Заявление – до директора на", wide=True),
    F("notification_email", "Е-поща за съобщения от Миграция", "email"),
    F("staff_count", "Наети служители (брой към момента)"),
    F("foreign_staff_count", "В т.ч. чужденци (брой)"),
    F("doc_city", "Град (за документите)"),
    F("doc_date", "Дата (за документите)", "date"),
    F("reg_no", "Вх. № на заявлението"),
    F("reg_date", "Дата на входиране", "date"),
    F("status", "Статус"),
    F("notes", "Бележки", "textarea", wide=True),
]

COUNTRY = [
    F("name", "Кратко име", required=True),
    F("name_official", "Официално име (BG)", help="напр. Република Узбекистан"),
    F("name_ru_gen", "Руски – родителен падеж", help="гражданин Республики Узбекистан"),
    F("name_ru_instr", "Руски – творителен падеж", help="выдан Республикой Узбекистан"),
    F("iso3", "Код в паспорта (3 букви)", help="напр. UZB"),
    F("aliases", "Други изписвания (със запетая)"),
]


class FormError(ValueError):
    def __init__(self, errors: dict):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def parse_form(fields: list[F], form) -> dict:
    """Validate request.form against field specs. Returns {column: value}. Raises FormError."""
    out, errors = {}, {}
    for f in fields:
        raw = form.get(f.name, "")
        raw = raw.strip() if isinstance(raw, str) else raw
        try:
            if f.kind == "date":
                out[f.name] = parse_date(raw)
            elif f.kind == "int":
                if raw == "":
                    out[f.name] = None
                else:
                    try:
                        out[f.name] = int(raw)
                    except ValueError:
                        raise ValueError("трябва да е цяло число")
            elif f.kind == "country":
                out[f.name] = int(raw) if raw else None
            elif f.kind == "bool":
                out[f.name] = 1 if raw in ("1", "on", "true", "yes") else 0
            elif f.kind == "gender":
                if raw not in ("", "M", "F"):
                    raise ValueError("невалиден пол")
                out[f.name] = raw
            else:
                out[f.name] = raw.replace("\r\n", "\n") if isinstance(raw, str) else ""
        except ValueError as exc:
            errors[f.name] = f"{f.label}: {exc}"
            continue
        if f.required and not out.get(f.name):
            errors[f.name] = f"{f.label}: задължително поле"
    if errors:
        raise FormError(errors)
    return out
