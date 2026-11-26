"""Bulgarian / Russian grammar helpers used by the document templates.

Everything here is pure and deterministic so it can be unit tested.
"""
from __future__ import annotations

import datetime as _dt

# ---------------------------------------------------------------- gender forms

# key -> (male form, female form)
CANDIDATE_FORMS = {
    "title": ("г-н", "г-жа"),
    "title_full": ("господин", "госпожа"),
    "roden": ("роден", "родена"),
    "grazhdanin": ("гражданин", "гражданка"),
    "naritsan": ("наричан", "наричана"),
    "dolupodpisan": ("долуподписаният", "долуподписаната"),
    "rabotnik": ("работник", "работничка"),
    # Russian half of the contract
    "ru_grazhdanin": ("гражданин", "гражданка"),
    "ru_rodilsya": ("родился", "родилась"),
    "ru_imenuemyi": ("именуемый", "именуемая"),
}

REPRESENTATIVE_FORMS = {
    "dolupodpisan": ("Долуподписаният", "Долуподписаната"),
    "v_kachestvoto": ("в качеството му", "в качеството ѝ"),
    "predstavlyavano_ot": ("представлявано от", "представлявано от"),
    "title": ("г-н", "г-жа"),
}


def gender_forms(gender: str | None, table: dict) -> dict:
    """Return {key: form} for gender 'M' or 'F'. Unknown gender -> 'роден/а' style."""
    out = {}
    for key, (male, female) in table.items():
        if gender == "F":
            out[key] = female
        elif gender == "M":
            out[key] = male
        else:
            out[key] = f"{male}/{female}"
    return out


# ---------------------------------------------------------------- numbers in words

_BG_UNITS = ["нула", "един", "два", "три", "четири", "пет", "шест", "седем", "осем", "девет",
             "десет", "единадесет", "дванадесет", "тринадесет", "четиринадесет", "петнадесет",
             "шестнадесет", "седемнадесет", "осемнадесет", "деветнадесет"]
_BG_TENS = {2: "двадесет", 3: "тридесет", 4: "четиридесет", 5: "петдесет", 6: "шестдесет"}

_RU_UNITS = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
             "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
             "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_RU_TENS = {2: "двадцать", 3: "тридцать", 4: "сорок", 5: "пятьдесят", 6: "шестьдесят"}


def words_bg(n: int) -> str:
    """Bulgarian words for 0..69 (masculine, as used with 'месеца', 'дни')."""
    if n < 0 or n > 69:
        return str(n)
    if n < 20:
        return _BG_UNITS[n]
    tens, unit = divmod(n, 10)
    return _BG_TENS[tens] if unit == 0 else f"{_BG_TENS[tens]} и {_BG_UNITS[unit]}"


def words_ru(n: int) -> str:
    """Russian words for 0..69 (masculine)."""
    if n < 0 or n > 69:
        return str(n)
    if n < 20:
        return _RU_UNITS[n]
    tens, unit = divmod(n, 10)
    return _RU_TENS[tens] if unit == 0 else f"{_RU_TENS[tens]} {_RU_UNITS[unit]}"


def months_bg(n: int) -> str:
    return "месец" if n == 1 else "месеца"


def months_ru(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "месяц"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "месяца"
    return "месяцев"


def days_ru(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "дня"
    return "дней"


def term_text_bg(months: int | None) -> str:
    """'36 месеца' -> used in 'Продължителност на договора'. 36 -> '3 години'."""
    if not months:
        return ""
    if months % 12 == 0:
        years = months // 12
        return "1 година" if years == 1 else f"{years} години"
    return f"{months} {months_bg(months)}"


# ---------------------------------------------------------------- formatting

def fmt_date(value) -> str:
    """ISO date (yyyy-mm-dd) or date -> dd.mm.yyyy. Empty -> ''."""
    if not value:
        return ""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.strftime("%d.%m.%Y")
    s = str(value).strip()
    try:
        return _dt.date.fromisoformat(s[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return s  # already free text, keep what the operator typed


def parse_date(value) -> str | None:
    """Accept dd.mm.yyyy, dd/mm/yyyy, yyyy-mm-dd; return ISO or None. Raises ValueError on garbage."""
    if value is None:
        return None
    s = str(value).strip().rstrip(".").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y"):
        try:
            return _dt.datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Невалидна дата: {value!r} (очаква се дд.мм.гггг)")


def fmt_money(value) -> str:
    """620.2 -> '620.20'."""
    if value in (None, ""):
        return ""
    try:
        return f"{float(str(value).replace(',', '.')):.2f}"
    except ValueError:
        return str(value)
