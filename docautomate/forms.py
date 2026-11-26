"""Form field definitions shared by the HTML forms and the save handlers."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .db import VISA_TYPES
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
    # задание, раздел 02: задължителни при създаване
    F("name_lat", "Име на латиница (по паспорт)", required=True),
    F("name_cyr", "Име на кирилица", required=True, help="Както ще се изписва в документите"),
    F("birth_date", "Дата на раждане", "date", required=True),
    F("passport_no", "Номер на паспорт", required=True),
    F("citizenship_id", "Страна на произход", "country", required=True),
    F("birth_place", "Място на раждане", required=True, help="Както е в паспорта, напр. Tashkent Region"),
    F("passport_issue_date", "Дата на издаване на паспорта", "date", required=True),
    F("passport_expiry", "Валидност на паспорта", "date", required=True),
    # незадължителни
    F("residence_address", "Адрес на местоживеене", wide=True,
      help="Влиза в декларацията за жилище"),
    F("lnch", "Номер ЛНЧ", help="Попълва се при наличност"),
    F("visa_type", "Тип виза", "select", options=(("", "—"),) + tuple((v, v) for v in VISA_TYPES),
      help="Избира кои бланки се генерират. Нужен е при генериране"),
    F("contact", "Контакт"),
    F("gender", "Пол", "gender", help="Нужен за роден/родена, г-н/г-жа в документите"),
    F("birth_country_id", "Държава на раждане", "country"),
    F("passport_issued_by", "Паспорт – издаден от", help="Празно = страната на произход"),
    F("phone", "Телефон", help="Заявление: „contact phone“"),
    F("address_bg", "Адрес в България (за заявлението)", wide=True),
    F("marital_status", "Семейно положение"),
    F("education", "Образование"),
    F("specialty", "Специалност"),
    F("qualification", "Квалификация"),
    F("notes", "Бележки", "textarea", wide=True, help="Само за вашата справка, не влиза в документите"),
]

EMPLOYER = [
    # задание, раздел 01: шестте задължителни полета
    F("name", "Име (с правната форма, напр. ЕООД)", required=True, wide=True),
    F("eik", "ЕИК", required=True, help="Само цифри; интервалите се махат автоматично"),
    F("address", "Седалище", required=True, wide=True),
    F("rep_name", "МОЛ – три имена", required=True, help="Материалноотговорното лице. Подписва документите"),
    F("phone", "Телефон за контакт", required=True),
    F("email", "Имейл за контакт", "email", required=True),
    # незадължителни
    F("rep_egn", "ЕГН на МОЛ", help="Обосновка и декларации"),
    F("rep_role", "Длъжност на МОЛ", help="напр. управител"),
    F("rep_gender", "Пол на МОЛ", "gender"),
    F("notes", "Бележки", "textarea", wide=True, help="Само за вашата справка, не влиза в документите"),
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
    F("contract_months", "Срок на договора (месеци)", "int", help="Трудов договор и Заявление. 36 = „3 години“"),
    F("probation_months", "Изпитателен срок (месеци)", "int", help="Трудов договор. Изписва се и с думи: 6 /шест/"),
    F("salary", "Основно месечно възнаграждение", help="Трудов договор. Само число, напр. 1077 или 620.20"),
    F("currency", "Валута", help="Пише се след сумата, напр. евро"),
    F("pay_day", "Заплатата се изплаща до (число от месеца)", help="Трудов договор, напр. 30"),
    F("leave_days", "Платен годишен отпуск (дни)", "int", help="Трудов договор, обикновено 20"),
    F("extra_leave_days", "Допълнителен платен отпуск (дни)", "int", help="Трудов договор, обикновено 0"),
    F("notice_months", "Предизвестие (месеци)", "int", help="Трудов договор. Изписва се и с думи: 3 /три/"),
    F("working_time", "Работно време", wide=True,
      help="Само за бланки с поле case.working_time. В основния трудов договор текстът е фиксиран (BG и RU)."),
    F("contract_extension", "Продължение на договор", "bool", help="Заявление: отметнато = „Да“, празно = „Не“"),
    F("contract_no", "№ на трудовия договор", help="Празно = линия за попълване на ръка"),
    F("contract_date", "Дата на трудовия договор", "date", help="Празно = линия за попълване на ръка"),
    F("start_date", "Дата на постъпване", "date", help="Само за бланки, които я ползват"),
    F("directorate", "Заявление: „До директора на“", wide=True, help="напр. дирекция „Миграция“ – МВР"),
    F("notification_email", "Е-поща за съобщения от Миграция", "email",
      help="Заявление, раздел „връчване на съобщенията“. Различна за всеки офис/партньор"),
    F("staff_count", "Брой наети служители във фирмата (сега)", help="Заявление. Пита се за всеки случай, защото се мени"),
    F("foreign_staff_count", "От тях чужденци (брой)", help="Заявление"),
    F("doc_city", "Град, който се пише в документите", help="Декларация, договор. напр. София"),
    F("doc_date", "Дата, която се пише в документите", "date", help="Обосновка, ДХ. Празно = линия за попълване на ръка"),
    F("reg_no", "Вх. № на заявлението", help="Контролен лист. Попълва се след входиране"),
    F("reg_date", "Дата на входиране", "date", help="Само за вашата справка"),
    F("status", "Статус", help="Само за вашата справка, не влиза в документите"),
    F("notes", "Бележки", "textarea", wide=True, help="Само за вашата справка, не влиза в документите"),
]

COUNTRY = [
    F("name", "Кратко име", required=True),
    F("name_official", "Официално име (BG)", help="напр. Република Узбекистан"),
    F("name_ru_gen", "Руски – родителен падеж", help="гражданин Республики Узбекистан"),
    F("name_ru_instr", "Руски – творителен падеж", help="выдан Республикой Узбекистан"),
    F("iso3", "Код в паспорта (3 букви)", help="напр. UZB"),
    F("aliases", "Други изписвания (със запетая)"),
]


# Short "where does this go" hints for fields whose label alone does not say it.
_HELP = {
    "name_lat": "Точно както в паспорта. Заявление, договор, обосновка",
    "birth_date": "дд.мм.гггг. Заявление, договор, обосновка",
    "birth_country_id": "Заявление: „държава/country“",
    "citizenship_id": "Всички документи. Нужна за „гражданин на …“ и руската част",
    "passport_no": "Всички документи",
    "passport_issue_date": "Не е в долните редове на паспорта – въведете ръчно",
    "passport_expiry": "Заявление, обосновка",
    "address_bg": "Заявление. Празно при първо подаване",
    "marital_status": "Заявление",
    "education": "Заявление",
    "specialty": "Заявление",
    "qualification": "Заявление",
    "name": "Точно както в Търговския регистър. Всички документи",
    "address": "Всички документи: „седалище и адрес на управление“",
    "rep_name": "Подписва договора, обосновката и декларацията",
    "rep_gender": "За „Долуподписаният/ата“ и „в качеството му/ѝ“",
    "phone": "Заявление",
    "email": "Заявление: „Телефон и електронна поща“",
    "title": "Всички документи, напр. Общ работник",
    "nkpd": "8 цифри. Заявление, договор, обосновка, ДХ",
    "workplace": "Договор, обосновка, ДХ, Заявление",
    "reporting_line": "ДХ: „Пряко подчинение“",
    "dh_purpose": "Един абзац",
}


def _with_help(fields):
    from dataclasses import replace
    return [f if f.help or f.name not in _HELP else replace(f, help=_HELP[f.name]) for f in fields]


CANDIDATE, EMPLOYER, POSITION = _with_help(CANDIDATE), _with_help(EMPLOYER), _with_help(POSITION)


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
            elif f.kind == "select":
                if raw not in {v for v, _ in f.options}:
                    raise ValueError("невалиден избор")
                out[f.name] = raw
            elif f.kind == "email":
                if raw and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw):
                    raise ValueError("невалиден имейл")
                out[f.name] = raw
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
